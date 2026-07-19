"""PipelineState — layered profiler runtime state and checkpoint.

The pipeline operator reads & edits checkpoint YAML between phases.
Phase methods use guard clauses to enforce ordering.  Large discovery
data (``broad_inventory``, ``shortlist``, ``source_tree``) is
externalized to JSON artifacts and referenced by ``_artifact`` keys
to keep the YAML human-reviewable.

This module holds the thin PipelineState checkpoint object and all
serialization/migration/validation logic.  Phase methods live in
``profiler/tools/pipeline_state.py`` (to be moved to
``profiler/pipeline/phases/`` in a future sprint).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from django.core.management.base import CommandError

from profiler.tools.domain_context import DomainContext
from profiler.tools.operational_model import Capability, OperationalModel
from profiler.tools.behavioral_spec import BehavioralSpec
from profiler.tools.behavioral_spec_validation import CoverageReport
from profiler.tools.validation_framework import ValidationRecord

logger = logging.getLogger(__name__)

# Fields that are externalized to JSON artifacts (not inlined in YAML).
# ``_to_dict_with_artifacts()`` iterates over these to drive serialization.
_ARTIFACT_FIELDS: set[str] = {
    "broad_inventory",
    "shortlist",
    "source_tree",
}


def _extract_approved_tabs(raw: dict[str, Any] | Any, default: Any = None) -> Any:
    """Find ``approved_tabs`` in a tab-selection artifact regardless of nesting depth.

    The old phased corpus workflow writes ``approved_tabs`` at the top level
    of ``tab_selection_<date>.json``, while the PipelineState ``discover``
    phase may nest it under a ``tab_selection.selection.approved_tabs`` path
    (or other multi-level keys).  This function searches recursively through
    the dict to find the first key named ``"approved_tabs"`` whose value is a
    dict mapping workbook codes to tab-name lists.

    Args:
        raw: Parsed tab-selection artifact (dict, list, or scalar).
        default: Fallback if no approved_tabs is found.

    Returns:
        The ``approved_tabs`` dict, or *default*.
    """
    if isinstance(raw, dict):
        # Direct hit — top-level approved_tabs
        if "approved_tabs" in raw:
            val = raw["approved_tabs"]
            if isinstance(val, dict):
                return val
            return default
        # Recurse into first dict value that looks like a wrapper
        for key, value in raw.items():
            result = _extract_approved_tabs(value, default=None)
            if result is not None:
                return result
    elif isinstance(raw, list):
        for item in raw:
            result = _extract_approved_tabs(item, default=None)
            if result is not None:
                return result
    return default


def _version_tuple(version: str) -> tuple[int, ...]:
    """Parse a semver string into a comparable tuple.

    Args:
        version: Semver string like ``"0.0.9"``.

    Returns:
        Tuple of integer version components.
    """
    return tuple(int(part) for part in version.split("."))


def _version_less_than(v1: str, v2: str) -> bool:
    """True if *v1* is strictly less than *v2*."""
    return _version_tuple(v1) < _version_tuple(v2)


def _version_less_eq(v1: str, v2: str) -> bool:
    """True if *v1* is less than or equal to *v2*."""
    return _version_tuple(v1) <= _version_tuple(v2)


def _col_index_to_letter(col_index: int) -> str:
    """Convert a 1-based column index to an Excel-style column letter."""
    letters = ""
    while col_index > 0:
        col_index, remainder = divmod(col_index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


_CHECKPOINT_CURRENT_VERSION = "0.3.0"

# Canonical phase ordering for downstream dependency tracking.
# Used by --force to determine which phases to invalidate.
_PHASE_ORDER: list[str] = [
    "discover",
    "score_and_select",
    "deep_profile",
    "derive_contracts",
    "scan_formulas",
    "validate",
]


# Registry: version_string -> list of migration functions.
# Each function takes and returns a raw dict (parsed YAML payload).
# Used to upgrade old checkpoint formats transparently on load.
def _migrate_v0_0_8_to_v0_0_9(raw: dict[str, Any]) -> dict[str, Any]:
    """Migration from checkpoint version 0.0.8 to 0.0.9.

    This is a minimal, safe migration that preserves existing payload while
    updating the checkpoint semantic version. It is intentionally a no-op for
    fields that are already compatible with 0.0.9. It exists to satisfy the
    test suite which expects a migration path from 0.0.8 to 0.0.9.

    Args:
        raw: Deserialized checkpoint dictionary.

    Returns:
        Migrated checkpoint dictionary with version bumped to 0.0.9 (actual
        data unchanged if already compatible).
    """
    # No structural changes required for this minimal migration. The driver will
    # bump the version after migrations anyway.
    return raw


def _migrate_v0_0_9_to_v0_1_0(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate legacy checkpoint to BPRS unified pipeline.

    Preserves old schema_contract and interaction_contract as legacy artifacts.
    Populates operational_model by deriving from existing discovery and domain
    knowledge fields.

    Args:
        raw: Deserialized checkpoint dictionary.

    Returns:
        Migrated checkpoint dictionary with version bumped and BPRS fields
        populated.
    """
    raw["legacy_schema_contract"] = raw.pop("schema_contract", None)
    raw["legacy_interaction_contract"] = raw.pop("interaction_contract", None)

    # Derive minimal operational model from existing fields
    domain = ""
    domain_raw = raw.get("domain_knowledge") or {}
    if isinstance(domain_raw, dict):
        domain = str(domain_raw.get("domain", ""))

    raw["operational_model"] = OperationalModel(
        source_id=domain,
        capabilities=[
            Capability(id="discovered_operations", owner=domain or "unknown")
        ],
    ).to_dict()

    return raw


def _migrate_v0_2_0_to_v0_3_0(raw: dict[str, Any]) -> dict[str, Any]:
    """Populate ``completed_phases`` from sentinel data.

    Before 0.3.0, phase completion was tracked implicitly via sentinel
    fields. This migration reads those sentinels and builds the explicit
    ``completed_phases`` list, handling the discover/score_and_select
    shortlist conflation.

    Args:
        raw: Deserialized checkpoint dictionary (pre-migration).

    Returns:
        Checkpoint dictionary with ``completed_phases`` populated.
    """
    if "completed_phases" in raw:
        # Already migrated — skip.
        return raw

    completed: list[str] = []
    discovery_raw = raw.get("discovery") or {}

    # discover: source_tree populated → completed
    # At migration time, source_tree is either {} (empty, no discover) or
    # {"_artifact": "..."} (artifact ref, discover ran).  {} is falsy.
    source_tree = discovery_raw.get("source_tree")
    if source_tree:
        completed.append("discover")

    # score_and_select: shortlist entries have score + scoring_rationale
    # (re-scored format from score_and_select, not raw discover output).
    # The conflation issue: discover() always writes to shortlist in raw
    # format (final_score-based), while score_and_select() overwrites with
    # a re-scored format containing score + scoring_rationale keys.
    shortlist_raw = discovery_raw.get("shortlist")
    if _is_scored_shortlist(shortlist_raw):
        completed.append("score_and_select")

    # deep_profile: deep_profile_index has entries → completed
    deep_raw = raw.get("deep_profile_index") or {}
    deep_entries = (
        deep_raw if isinstance(deep_raw, list) else deep_raw.get("entries") or []
    )
    if deep_entries:
        completed.append("deep_profile")

    # derive_contracts: schema_contract populated → completed
    # At migration time, schema_contract is either None (empty) or
    # {"_artifact": "..."} (artifact ref).  None is falsy.
    schema_contract = raw.get("schema_contract")
    if schema_contract:
        completed.append("derive_contracts")

    raw["completed_phases"] = completed
    return raw


def _is_scored_shortlist(shortlist_raw: Any) -> bool:
    """Check if a shortlist contains re-scored entries (``score_and_select`` format).

    ``discover()`` writes shortlist entries with ``final_score`` / ``breakdown_summary``
    keys from raw cohort corpus output.  ``score_and_select()`` overwrites entries
    with ``score`` / ``scoring_rationale`` keys from domain-aware re-scoring.

    Returns:
        True if the shortlist has at least one entry with both ``score`` and
        ``scoring_rationale`` keys.
    """
    if isinstance(shortlist_raw, list):
        return any(
            isinstance(entry, dict)
            and "score" in entry
            and "scoring_rationale" in entry
            for entry in shortlist_raw
        )
    if isinstance(shortlist_raw, dict):
        entries = shortlist_raw.get("selected") or []
        return any(
            isinstance(entry, dict)
            and "score" in entry
            and "scoring_rationale" in entry
            for entry in entries
        )
    return False


_CHECKPOINT_MIGRATIONS: dict[str, list[Callable[[dict], dict]]] = {
    # Migrations keyed by the target version; when upgrading from a(version) < key
    # and the key is <= current, apply the migrations to upgrade payloads.
    "0.0.9": [_migrate_v0_0_8_to_v0_0_9],
    "0.1.0": [_migrate_v0_0_9_to_v0_1_0],
    # 0.2.0: BehavioralSpec field added — deserializer handles None gracefully.
    "0.2.0": [
        lambda raw: raw,
    ],
    # 0.3.0: completed_phases registry added. Populate from sentinel data.
    "0.3.0": [_migrate_v0_2_0_to_v0_3_0],
}


# ---------------------------------------------------------------------------
# A. Dataclass layer
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryState:
    """Machine-learned profiler findings (Layer 1).

    Each field is small metadata — never raw grid data.  Large fields
    (``broad_inventory``, ``shortlist``, ``source_tree``) are
    externalized to JSON artifacts during checkpoint save.
    """

    source_tree: dict[str, Any] | None = field(default=None)
    workbook_index: list[dict[str, Any]] = field(default_factory=list)
    broad_inventory: list[dict[str, Any]] = field(default_factory=list)
    shortlist: list[dict[str, Any]] | None = field(default=None)
    approved_tabs: dict[str, list[str]] | None = field(default=None)

    def __post_init__(self) -> None:
        """Validate field types on construction."""
        if self.source_tree is not None and not isinstance(self.source_tree, dict):
            raise TypeError(
                f"source_tree must be dict or None, "
                f"got {type(self.source_tree).__name__}"
            )
        if not isinstance(self.workbook_index, list):
            raise TypeError(
                f"workbook_index must be list, got {type(self.workbook_index).__name__}"
            )


@dataclass
class DeepProfileIndex:
    """References to external deep-profile JSON artifacts.

    The ``entries`` list holds metadata and artifact paths for each
    deep-profiled tab, keeping the checkpoint YAML compact.
    """

    entries: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DomainKnowledge:
    """Human-provided / confirmed domain knowledge (Layer 2).

    This is intentionally a plain-dict mirror of ``DomainContext`` so that it
    round-trips through YAML without requiring the ``DomainContext`` nested
    dataclass structure.  The PipelineState owns a *copy* of the domain
    context data; ``DomainContext`` remains the authoritative input type.
    """

    domain: str = ""
    description: str = ""
    vocabulary: dict[str, list[str]] = field(
        default_factory=lambda: {
            "operational": [],
            "reference": [],
            "support": [],
            "derived": [],
        }
    )
    year_scope: dict[str, Any] = field(
        default_factory=lambda: {
            "active": [],
            "archived": [],
            "forward": [],
        }
    )
    deduplication: dict[str, Any] = field(
        default_factory=lambda: {
            "strategy": "latest_year",
            "exceptions": [],
        }
    )
    entities: list[dict[str, Any]] = field(default_factory=list)
    glossary: dict[str, str] = field(default_factory=dict)
    scope_notes: str = ""

    def __post_init__(self) -> None:
        """Validate required dictionary keys on construction."""
        required_vocab_keys = {"operational", "reference", "support", "derived"}
        if not required_vocab_keys.issubset(self.vocabulary.keys()):
            raise ValueError(
                f"vocabulary must contain keys {required_vocab_keys}, "
                f"got {set(self.vocabulary.keys())}"
            )
        required_year_keys = {"active", "archived", "forward"}
        if not required_year_keys.issubset(self.year_scope.keys()):
            raise ValueError(
                f"year_scope must contain keys {required_year_keys}, "
                f"got {set(self.year_scope.keys())}"
            )

    # ------------------------------------------------------------------ #
    # DomainContext → DomainKnowledge bridge
    # ------------------------------------------------------------------ #

    @classmethod
    def from_domain_context(cls, ctx: DomainContext | None) -> DomainKnowledge:
        """Create a ``DomainKnowledge`` from a ``DomainContext``.

        Parameters
        ----------
        ctx : DomainContext | None
            Domain context instance.  If ``None``, returns an empty instance.

        Returns
        -------
        DomainKnowledge
            Flat-dict representation of the same domain knowledge.
        """
        if ctx is None:
            return cls()
        return cls(
            domain=ctx.domain,
            description=ctx.description,
            vocabulary={
                "operational": list(ctx.vocabulary.operational),
                "reference": list(ctx.vocabulary.reference),
                "support": list(ctx.vocabulary.support),
                "derived": list(ctx.vocabulary.derived),
            },
            year_scope={
                "active": list(ctx.year_scope.active),
                "archived": list(ctx.year_scope.archived),
                "forward": list(ctx.year_scope.forward),
            },
            deduplication={
                "strategy": ctx.deduplication.strategy,
                "exceptions": list(ctx.deduplication.exceptions),
            },
            entities=list(ctx.entities),
            glossary=dict(ctx.glossary),
            scope_notes=ctx.scope_notes,
        )


@dataclass
class DecisionRecord:
    """A recorded decision made during pipeline execution.

    Each decision captures what was chosen, why, and with what confidence
    so that the operator can audit and override later.
    """

    decision_id: str = ""
    timestamp: str = ""  # ISO 8601 string
    phase: str = ""  # e.g. "score_and_select", "derive_contracts"
    description: str = ""  # Human-readable what-was-decided
    outcome: str = ""  # e.g. "approved", "rejected", "deferred"
    confidence: float = 0.0  # 0.0–1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineState:
    """Layered profiler runtime state.

    Attributes:
        version: Format version string.
        discovery: Machine discoveries (source tree, workbook index,
            inventory, shortlist, approved tabs).
        deep_profile_index: External references to deep-profile JSON
            artifacts.
        domain_knowledge: Human-provided domain knowledge (vocabulary,
            year scope, entities, glossary).
        schema_contract: Derived data contract (models, fields, FKs)
            — read-only in checkpoint.
        interaction_contract: Derived UI/workflow contract — read-only
            in checkpoint.
        operational_model: Derived BPRS operational model (capabilities,
            workflows, commands, events, invariants).
        validation_record: Human review gate output with approvals per
            layer.
        coverage_report: Auto-computed coverage metrics for the
            operational model.
    """

    # Schema version for checkpoint migration. Independent of the package version in pyproject.toml
    # -- see Agents.md "Schema versions".
    version: str = "0.2.0"
    discovery: DiscoveryState = field(default_factory=DiscoveryState)
    deep_profile_index: DeepProfileIndex = field(default_factory=DeepProfileIndex)
    domain_knowledge: DomainKnowledge = field(default_factory=DomainKnowledge)
    schema_contract: dict[str, Any] | None = None
    interaction_contract: dict[str, Any] | None = None
    decisions: list[DecisionRecord] = field(default_factory=list)

    # Path to profiler-signals YAML artifact (persisted in checkpoint).
    profiler_signals_path: str | None = None

    # BPRS unified pipeline fields.
    operational_model: OperationalModel | None = None
    behavioral_spec: BehavioralSpec | None = None
    validation_record: ValidationRecord | None = None
    coverage_report: CoverageReport | None = None
    formula_scan_results: dict[str, Any] | None = None
    test_scaffold: str | None = field(default=None, repr=False)
    doc_scaffold: str | None = field(default=None, repr=False)

    # Operator-defined priority stack rank for workflows
    operator_priority: dict[str, int] = field(default_factory=dict)
    # Maps workflow_id -> priority rank (1 = highest)

    # Registry of completed pipeline phases.
    # Used by _run_all and single-phase guards in run_pipeline_state.py
    # to determine whether a phase has already been executed.
    completed_phases: list[str] = field(default_factory=list)

    # Provenance tracking for all artifacts
    artifact_provenance: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Maps artifact_key -> {"source": str, "signals": list, "recorded_at": str}

    # Runtime-only fields (not serialized to checkpoint).
    _config: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    _out_dir: Path | None = field(default=None, repr=False, compare=False)
    _date_stamp: str | None = field(default=None, repr=False, compare=False)
    _signals_output_path: Path | None = field(default=None, repr=False, compare=False)
    _signals_cache: dict[tuple[str, str], dict[str, Any]] | None = field(
        default=None, repr=False, compare=False
    )
    _checkpoint_dir: Path | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate field types on construction."""
        if self.version and not isinstance(self.version, str):
            raise TypeError(f"version must be str, got {type(self.version).__name__}")
        if self.discovery is not None and not isinstance(
            self.discovery, DiscoveryState
        ):
            raise TypeError(
                f"discovery must be DiscoveryState, got {type(self.discovery).__name__}"
            )
        if self.domain_knowledge is not None and not isinstance(
            self.domain_knowledge, DomainKnowledge
        ):
            raise TypeError(
                f"domain_knowledge must be DomainKnowledge, "
                f"got {type(self.domain_knowledge).__name__}"
            )

    # ------------------------------------------------------------------
    # Runtime configuration
    # ------------------------------------------------------------------

    def configure(
        self,
        *,
        config: dict[str, Any] | None = None,
        out_dir: str | Path | None = None,
        date_stamp: str | None = None,
        signals_output_path: str | Path | None = None,
    ) -> PipelineState:
        """Set runtime configuration for pipeline execution.

        These fields are stored privately (not serialized to checkpoint)
        and are consumed by phase methods that need them.

        Args:
            config: Parsed cohort corpus config dict.
            out_dir: Directory for profiler JSON artifacts.
            date_stamp: Timestamp for artifact filenames (ISO date string).
            signals_output_path: Path for profiler-signals YAML artifact.

        Returns:
            PipelineState: Self for chaining.
        """
        self._config = config or self._config or {}
        self._out_dir = (
            Path(out_dir)
            if out_dir
            else (self._out_dir or Path("data/profile_snapshots"))
        )
        self._date_stamp = date_stamp or self._date_stamp or date.today().isoformat()
        if signals_output_path:
            self._signals_output_path = Path(signals_output_path)
        return self

    # ------------------------------------------------------------------
    # Profiler signals
    # ------------------------------------------------------------------

    def load_profiler_signals(
        self,
    ) -> dict[tuple[str, str], dict[str, Any]] | None:
        """Lazy-resolve profiler signals from the checkpoint-relative path.

        The signals artifact is a YAML file referenced by
        ``profiler_signals_path`` (stored in the checkpoint).  On first call
        the file is loaded, parsed, and cached as a dict keyed by
        ``(workbook_code, tab_title)`` for fast lookup.  Subsequent calls
        return the cached dict.

        Returns:
            Dict mapping ``(workbook_code, tab_title)`` to the signal entry,
            or ``None`` if no signals path is configured or the file is
            missing.
        """
        if self._signals_cache is not None:
            return self._signals_cache

        if not self.profiler_signals_path:
            return None

        signals_path = Path(self.profiler_signals_path)
        if not signals_path.is_absolute() and self._out_dir:
            signals_path = self._out_dir.parent / signals_path
        if not signals_path.exists():
            logger.warning(
                "profiler signals artifact not found at %s",
                signals_path,
            )
            return None

        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("PyYAML not available — cannot load profiler signals")
            return None

        try:
            raw = yaml.safe_load(signals_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(
                "failed to load profiler signals from %s: %s",
                signals_path,
                exc,
            )
            return None

        if not isinstance(raw, dict):
            return None

        signals_list = raw.get("signals") or []
        cache: dict[tuple[str, str], dict[str, Any]] = {}
        for entry in signals_list:
            if isinstance(entry, dict):
                key = (
                    str(entry.get("workbook_code", "")),
                    str(entry.get("tab_title", "")),
                )
                if key[0] or key[1]:
                    cache[key] = entry

        self._signals_cache = cache
        return cache

    # ------------------------------------------------------------------
    # Decision recording
    # ------------------------------------------------------------------

    def record_decision(
        self,
        decision_id: str,
        phase: str,
        description: str,
        outcome: str,
        confidence: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> DecisionRecord:
        """Record a pipeline decision and append it to the decisions list.

        Args:
            decision_id: Unique identifier for this decision.
            phase: Pipeline phase that produced this decision.
            description: Human-readable explanation.
            outcome: Decision outcome (approved/rejected/deferred).
            confidence: Confidence score 0.0–1.0.
            metadata: Optional structured metadata.

        Returns:
            The appended DecisionRecord.
        """
        import datetime

        record = DecisionRecord(
            decision_id=decision_id,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            phase=phase,
            description=description,
            outcome=outcome,
            confidence=confidence,
            metadata=metadata or {},
        )
        self.decisions.append(record)
        return record

    # ------------------------------------------------------------------
    # Artifact provenance
    # ------------------------------------------------------------------

    def record_artifact_provenance(
        self,
        artifact_key: str,
        source: str,
        signals: list[dict[str, Any]] | None = None,
    ) -> None:
        """Record how an artifact was derived.

        Args:
            artifact_key: Identifier for the artifact (e.g. 'workflow:weekly_harvest_planning').
            source: 'inferred', 'elicited', or 'hybrid'.
            signals: Optional list of inference signals.
        """
        import datetime

        self.artifact_provenance[artifact_key] = {
            "source": source,
            "signals": signals or [],
            "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    def get_artifact_provenance(self, artifact_key: str) -> dict[str, Any] | None:
        """Retrieve provenance for an artifact.

        Args:
            artifact_key: Identifier for the artifact.

        Returns:
            The provenance dict or ``None`` if not found.
        """
        return self.artifact_provenance.get(artifact_key)

    # ------------------------------------------------------------------
    # Checkpoint I/O
    # ------------------------------------------------------------------

    def save_checkpoint(self, path: str | Path) -> None:
        """Serialize state to a YAML checkpoint with ``_artifact`` references.

        Large fields (``broad_inventory``, ``shortlist``, ``source_tree``)
        are written to sibling JSON files and referenced by ``_artifact``
        keys, keeping the YAML human-reviewable.

        Parameters
        ----------
        path : str | Path
            Filesystem path for the checkpoint YAML.
        """
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Build a plain dict representation with artifact references
        payload = self._to_dict_with_artifacts(file_path.parent)

        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise CommandError(
                "PyYAML is required for checkpoint serialization."
            ) from exc

        file_path.write_text(
            yaml.safe_dump(
                payload, sort_keys=False, allow_unicode=True, default_flow_style=False
            ),
            encoding="utf-8",
        )
        logger.info("saved checkpoint %s", file_path)

    @classmethod
    def load(cls, path: str | Path) -> PipelineState:
        """Load a checkpoint from YAML, resolving ``_artifact`` references.

        Parameters
        ----------
        path : str | Path
            Path to the checkpoint YAML.

        Returns
        -------
        PipelineState
            Reconstructed pipeline state.

        Raises
        ------
        CommandError
            If the YAML is malformed or resolves to a non-dict.
        """
        file_path = Path(path)
        if not file_path.exists():
            logger.info("checkpoint not found at %s — returning empty state", file_path)
            return cls()

        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise CommandError(
                "PyYAML is required for checkpoint deserialization."
            ) from exc

        try:
            raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CommandError(
                f"Failed to parse checkpoint YAML at {file_path}: {exc}"
            ) from exc

        if not isinstance(raw, dict):
            raise CommandError(f"Checkpoint at {file_path} is not a YAML mapping.")

        # Resolve _artifact references back into inline data
        base_dir = file_path.parent
        resolved = _resolve_artifacts(raw, base_dir)

        # Apply format migrations after resolving artifacts so migration
        # functions see the actual data, not artifact-reference dicts.
        resolved = cls._apply_migrations(resolved)
        if not isinstance(resolved, dict):
            raise CommandError(f"Checkpoint at {file_path} resolved to non-dict.")

        instance = cls._from_resolved_dict(resolved, base_dir=base_dir)
        instance._checkpoint_dir = base_dir
        return instance

    @classmethod
    def load_or_create(
        cls,
        config_path: str | Path,
        checkpoint_path: str | Path | None = None,
        *,
        domain_context: DomainContext | None = None,
        out_dir: str | Path | None = None,
        date_stamp: str | None = None,
        force: bool = False,
    ) -> PipelineState:
        """Load existing checkpoint or create fresh from config.

        Parameters
        ----------
        config_path : str | Path
            Path to a JSON config file (e.g. ``cohort_corpus.json``).
        checkpoint_path : str | Path | None
            Path to an existing checkpoint YAML.  If ``None``, derived
            from ``config_path`` by replacing the suffix.
        domain_context : DomainContext | None
            Optional domain context to seed domain knowledge.
        out_dir : str | Path | None
            Output directory for profiler artifacts.
        date_stamp : str | None
            ISO date string for artifact filenames.
        force : bool
            If ``True``, suppress the stale-artifact warning and proceed.

        Returns
        -------
        PipelineState
        """
        if checkpoint_path is None:
            checkpoint_path = Path(str(config_path)).with_suffix(".yaml")
        checkpoint_path = Path(checkpoint_path)

        # Read config JSON once
        config_file = Path(config_path)
        config: dict[str, Any] = {}
        if config_file.exists():
            try:
                raw_config = json.loads(config_file.read_text(encoding="utf-8"))
                config = {k: v for k, v in raw_config.items() if not k.startswith("_")}
            except (json.JSONDecodeError, OSError):
                config = {}

        if checkpoint_path.exists():
            state = cls.load(checkpoint_path)
        elif domain_context is not None:
            state = cls(
                domain_knowledge=DomainKnowledge.from_domain_context(domain_context),
            )
        else:
            state = cls()
            domain_val = config.get("domain")
            if domain_val:
                state.domain_knowledge.domain = str(domain_val)

        state.configure(config=config, out_dir=out_dir, date_stamp=date_stamp)

        # Stale-artifact detection: warn when pre-existing discover-phase
        # artifacts exist in the output directory and no checkpoint is
        # being resumed.  Old artifacts can silently corrupt ``discover()``
        # by supplying stale discovery data instead of performing a fresh
        # run.  Pass ``--force`` (or ``force=True``) to suppress.
        if not checkpoint_path.exists() and not force:
            resolved_out = state._out_dir or Path("data/profile_snapshots")
            if resolved_out.exists() and resolved_out.is_dir():
                stale_artifacts = sorted(resolved_out.glob("tab_selection_*.json"))
                if stale_artifacts:
                    logger.warning(
                        "Stale discover-phase artifacts found in %s "
                        "(e.g. %s). These may cause PipelineState to load "
                        "stale discovery data instead of performing a fresh "
                        "discovery.  Run 'make clean-profile' or pass "
                        "--force to suppress this warning.",
                        resolved_out,
                        stale_artifacts[0].name,
                    )

        return state

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def _to_dict_with_artifacts(self, base_dir: Path) -> dict[str, Any]:
        """Convert state to a plain dict, writing large lists to external JSON."""
        payload: dict[str, Any] = {
            "version": self.version,
            "discovery": {},
            "domain_knowledge": asdict(self.domain_knowledge),
            "decisions": [asdict(d) for d in self.decisions],
        }

        discovery = self.discovery
        disc: dict[str, Any] = {}

        # Small fields inline (handle None defaults)
        disc["workbook_index"] = discovery.workbook_index

        # approved_tabs: preserve None sentinel for guard clauses
        if discovery.approved_tabs is None:
            disc["approved_tabs"] = None
        else:
            disc["approved_tabs"] = discovery.approved_tabs

        # source_tree → external JSON artifact (full drive tree, not small metadata)
        if discovery.source_tree:
            artifact_path = base_dir / "pipeline-state-source-tree.json"
            artifact_path.write_text(
                json.dumps(discovery.source_tree, indent=2), encoding="utf-8"
            )
            disc["source_tree"] = {
                "_artifact": str(artifact_path.relative_to(base_dir))
            }
        else:
            disc["source_tree"] = {}

        # Remaining artifact fields → external JSON (preserve None sentinels)
        for field_name in sorted(_ARTIFACT_FIELDS - {"source_tree"}):
            data = getattr(discovery, field_name)
            if data:
                artifact_path = base_dir / f"pipeline-state-{field_name}.json"
                artifact_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                disc[field_name] = {
                    "_artifact": str(artifact_path.relative_to(base_dir))
                }
            elif data is None:
                disc[field_name] = None  # preserve sentinel for guard clauses
            else:
                disc[field_name] = []

        payload["discovery"] = disc

        # Deep profile index as artifact reference
        if self.deep_profile_index.entries:
            artifact_path = base_dir / "pipeline-state-deep-profiles.json"
            artifact_path.write_text(
                json.dumps(self.deep_profile_index.entries, indent=2),
                encoding="utf-8",
            )
            payload["deep_profile_index"] = {
                "_artifact": str(artifact_path.relative_to(base_dir))
            }
        else:
            payload["deep_profile_index"] = {"entries": []}

        # Profiler signals path (simple path string, no externalization needed)
        if self.profiler_signals_path:
            payload["profiler_signals_path"] = self.profiler_signals_path

        # Derived contracts as artifact references
        if self.schema_contract:
            # Write the contract artifact next to the checkpoint and reference it
            # relative to the checkpoint directory to ensure checkpoint-relative
            # paths (no hard-coded build/ prefixes).
            contract_artifact_path = base_dir / "schema-contract.json"
            payload["schema_contract"] = {
                "_artifact": str(contract_artifact_path.relative_to(base_dir))
            }
            _write_contract_artifact(self.schema_contract, contract_artifact_path)
        if self.interaction_contract:
            contract_artifact_path = base_dir / "interaction-contract.json"
            payload["interaction_contract"] = {
                "_artifact": str(contract_artifact_path.relative_to(base_dir))
            }
            _write_contract_artifact(self.interaction_contract, contract_artifact_path)

        # BPRS: operational model as artifact reference
        if self.operational_model:
            op_model_path = base_dir / "operational-model.json"
            op_model_path.write_text(
                json.dumps(self.operational_model.to_dict(), indent=2),
                encoding="utf-8",
            )
            payload["operational_model"] = {
                "_artifact": str(op_model_path.relative_to(base_dir))
            }
        else:
            payload["operational_model"] = None

        # MWBS: behavioral spec as artifact reference
        if self.behavioral_spec:
            bs_path = base_dir / "behavioral-spec.json"
            bs_path.write_text(
                json.dumps(self.behavioral_spec.to_dict(), indent=2),
                encoding="utf-8",
            )
            payload["behavioral_spec"] = {
                "_artifact": str(bs_path.relative_to(base_dir))
            }
        else:
            payload["behavioral_spec"] = None

        # BPRS: validation record inline (small)
        if self.validation_record:
            payload["validation_record"] = self.validation_record.to_dict()
        else:
            payload["validation_record"] = None

        # BPRS: coverage report inline (small)
        if self.coverage_report:
            payload["coverage_report"] = self.coverage_report.to_dict()
        else:
            payload["coverage_report"] = None

        # BPRS: test_scaffold inline (string, not an artifact)
        if self.test_scaffold:
            payload["test_scaffold"] = self.test_scaffold
        else:
            payload["test_scaffold"] = None

        # BPRS: doc_scaffold inline (string, not an artifact)
        if self.doc_scaffold:
            payload["doc_scaffold"] = self.doc_scaffold
        else:
            payload["doc_scaffold"] = None

        # Operator priority and artifact provenance (small, inline)
        payload["operator_priority"] = dict(self.operator_priority)
        payload["artifact_provenance"] = dict(self.artifact_provenance)

        # Completed phases registry (small, inline)
        payload["completed_phases"] = list(self.completed_phases)

        return payload

    @classmethod
    def _apply_migrations(cls, raw: dict[str, Any]) -> dict[str, Any]:
        """Apply checkpoint format migrations from stored version to current.

        Called in ``load()`` after YAML parsing, before ``_from_resolved_dict()``.

        Args:
            raw: Parsed checkpoint dict.

        Returns:
            Migrated dict with ``version`` bumped to current.
        """
        version = raw.get("version", "0.0.0")
        if not isinstance(version, str):
            version = "0.0.0"

        for from_ver in sorted(_CHECKPOINT_MIGRATIONS):
            if _version_less_than(version, from_ver) and _version_less_eq(
                from_ver, _CHECKPOINT_CURRENT_VERSION
            ):
                for migrate_fn in _CHECKPOINT_MIGRATIONS[from_ver]:
                    raw = migrate_fn(raw)

        raw["version"] = _CHECKPOINT_CURRENT_VERSION
        return raw

    @classmethod
    def _from_resolved_dict(
        cls, raw: dict[str, Any], base_dir: Path | None = None
    ) -> PipelineState:
        """Reconstruct a PipelineState from a fully-resolved plain dict.

        Args:
            raw: Deserialized checkpoint dictionary with artifact references
                already resolved.
            base_dir: Base directory for resolving contract artifacts.
                When provided, ``schema_contract`` and ``interaction_contract``
                are eagerly resolved from artifact files.
        """
        discovery_raw = raw.get("discovery") or {}
        domain_raw = raw.get("domain_knowledge") or {}
        deep_raw = raw.get("deep_profile_index") or {}
        decisions_raw = raw.get("decisions", [])

        # Preserve None sentinels — guard clauses distinguish
        # "not yet populated" (None) from "populated but empty" ([]/{}).
        shortlist_raw = discovery_raw.get("shortlist")
        shortlist = (
            list(shortlist_raw) if isinstance(shortlist_raw, list) else shortlist_raw
        )
        approved_tabs_raw = discovery_raw.get("approved_tabs")
        approved_tabs = (
            dict(approved_tabs_raw)
            if isinstance(approved_tabs_raw, dict)
            else approved_tabs_raw
        )

        # workbook_index: either a list of record dicts, or a dict with "records" key.
        raw_index = discovery_raw.get("workbook_index") or []
        if isinstance(raw_index, dict) and "records" in raw_index:
            index_data = raw_index["records"]
        elif (
            isinstance(raw_index, list) and raw_index and isinstance(raw_index[0], dict)
        ):
            index_data = raw_index
        else:
            index_data = []

        broad_inventory_raw = discovery_raw.get("broad_inventory") or []
        if isinstance(broad_inventory_raw, dict):
            broad_inventory = broad_inventory_raw.get("results", [])
        elif isinstance(broad_inventory_raw, list):
            broad_inventory = broad_inventory_raw
        else:
            broad_inventory = []

        discovery = DiscoveryState(
            source_tree=discovery_raw.get("source_tree") or {},
            workbook_index=list(index_data),
            broad_inventory=broad_inventory,
            shortlist=shortlist,
            approved_tabs=approved_tabs,
        )

        # deep_profile_index may be a list (resolved artifact) or a dict
        if isinstance(deep_raw, list):
            deep_entries = deep_raw
        else:
            deep_entries = deep_raw.get("entries") or []
        deep_profile_index = DeepProfileIndex(
            entries=list(deep_entries),
        )

        domain_knowledge = DomainKnowledge(
            domain=str(domain_raw.get("domain", "")),
            description=str(domain_raw.get("description", "")),
            year_scope=domain_raw.get("year_scope")
            or {"active": [], "archived": [], "forward": []},
            deduplication=domain_raw.get("deduplication")
            or {"strategy": "latest_year", "exceptions": []},
            entities=list(domain_raw.get("entities") or []),
            vocabulary=domain_raw.get("vocabulary")
            or {"operational": [], "reference": [], "support": [], "derived": []},
            glossary=dict(domain_raw.get("glossary") or {}),
            scope_notes=str(domain_raw.get("scope_notes", "")),
        )

        decisions = [DecisionRecord(**d) for d in decisions_raw]

        # Contract resolution — resolve artifact references eagerly
        schema_contract: dict[str, Any] | None = None
        interaction_contract: dict[str, Any] | None = None
        if base_dir is not None:
            schema_raw = raw.get("schema_contract")
            if schema_raw:
                resolved = _resolve_artifacts(schema_raw, base_dir)
                if isinstance(resolved, dict) and resolved:
                    schema_contract = resolved

            interaction_raw = raw.get("interaction_contract")
            if interaction_raw:
                resolved = _resolve_artifacts(interaction_raw, base_dir)
                if isinstance(resolved, dict) and resolved:
                    interaction_contract = resolved

        # Profiler signals path — preserved from checkpoint
        profiler_signals_path = raw.get("profiler_signals_path") or None

        # BPRS: operational model resolution
        op_model_raw = raw.get("operational_model")
        operational_model: OperationalModel | None = None
        if op_model_raw:
            resolved_op_model = (
                _resolve_artifacts(op_model_raw, base_dir) if base_dir else op_model_raw
            )
            if isinstance(resolved_op_model, dict):
                operational_model = OperationalModel.from_dict(resolved_op_model)

        # MWBS: behavioral spec resolution
        bs_raw = raw.get("behavioral_spec")
        behavioral_spec: BehavioralSpec | None = None
        if bs_raw:
            resolved_bs = _resolve_artifacts(bs_raw, base_dir) if base_dir else bs_raw
            if isinstance(resolved_bs, dict):
                behavioral_spec = BehavioralSpec.from_dict(resolved_bs)

        # BPRS: validation record inline (small)
        validation_record: ValidationRecord | None = None
        val_raw = raw.get("validation_record")
        if val_raw and isinstance(val_raw, dict):
            validation_record = ValidationRecord.from_dict(val_raw)

        # BPRS: coverage report inline (small)
        coverage_report: CoverageReport | None = None
        cov_raw = raw.get("coverage_report")
        if cov_raw and isinstance(cov_raw, dict):
            coverage_report = CoverageReport.from_dict(cov_raw)

        # BPRS: test_scaffold inline (string)
        test_scaffold_raw = raw.get("test_scaffold")
        test_scaffold: str | None = (
            str(test_scaffold_raw) if test_scaffold_raw else None
        )

        # BPRS: doc_scaffold inline (string)
        doc_scaffold_raw = raw.get("doc_scaffold")
        doc_scaffold: str | None = str(doc_scaffold_raw) if doc_scaffold_raw else None

        # Operator priority and artifact provenance (small, inline)
        operator_priority = dict(raw.get("operator_priority") or {})
        artifact_provenance = dict(raw.get("artifact_provenance") or {})

        # Completed phases registry (small, inline)
        completed_phases_raw = raw.get("completed_phases")
        completed_phases = (
            list(completed_phases_raw) if isinstance(completed_phases_raw, list) else []
        )

        return cls(
            version=str(raw.get("version", "0.3.0")),
            discovery=discovery,
            deep_profile_index=deep_profile_index,
            domain_knowledge=domain_knowledge,
            schema_contract=schema_contract,
            interaction_contract=interaction_contract,
            decisions=decisions,
            profiler_signals_path=(
                str(profiler_signals_path) if profiler_signals_path else None
            ),
            operational_model=operational_model,
            behavioral_spec=behavioral_spec,
            validation_record=validation_record,
            coverage_report=coverage_report,
            test_scaffold=test_scaffold,
            doc_scaffold=doc_scaffold,
            operator_priority=operator_priority,
            artifact_provenance=artifact_provenance,
            completed_phases=completed_phases,
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """Validate checkpoint internal consistency.

        Checks:
        1. DomainKnowledge structure (vocabulary keys, year_scope keys)
        2. ``approved_tabs`` workbook codes exist in ``workbook_index``
        3. No duplicate tab entries across workbooks
        4. Decision records have required fields
        5. ``approved_tabs`` values are lists of strings

        Returns:
            List of error messages.  Empty list means valid.
        """
        errors: list[str] = []

        # 1. DomainKnowledge structure
        try:
            required_vocab = {"operational", "reference", "support", "derived"}
            vocab_keys = set(self.domain_knowledge.vocabulary.keys())
            if not required_vocab.issubset(vocab_keys):
                errors.append(
                    f"domain_knowledge.vocabulary missing keys: "
                    f"{required_vocab - vocab_keys}"
                )
        except AttributeError as exc:
            errors.append(f"domain_knowledge.vocabulary structure error: {exc}")

        try:
            required_year = {"active", "archived", "forward"}
            year_keys = set(self.domain_knowledge.year_scope.keys())
            if not required_year.issubset(year_keys):
                errors.append(
                    f"domain_knowledge.year_scope missing keys: "
                    f"{required_year - year_keys}"
                )
        except AttributeError as exc:
            errors.append(f"domain_knowledge.year_scope structure error: {exc}")

        # 2. approved_tabs workbook_code cross-reference
        approved = self.discovery.approved_tabs
        if approved is not None and isinstance(approved, dict):
            index_entries = self.discovery.workbook_index
            if isinstance(index_entries, dict) and "records" in index_entries:
                index_entries = index_entries["records"]
            workbook_codes = {
                str(wb.get("workbook_code", ""))
                for wb in index_entries
                if isinstance(wb, dict) and wb.get("workbook_code")
            }
            for wb_code, tab_list in approved.items():
                if wb_code not in workbook_codes:
                    errors.append(
                        f"approved_tabs workbook code '{wb_code}' "
                        f"not found in workbook_index"
                    )
                if not isinstance(tab_list, list):
                    errors.append(f"approved_tabs['{wb_code}'] is not a list")
                else:
                    for tab_name in tab_list:
                        if not isinstance(tab_name, str):
                            errors.append(
                                f"approved_tabs['{wb_code}'] contains "
                                f"non-string entry: {tab_name!r}"
                            )

            # 3. No duplicate tab entries across workbooks
            seen_tabs: set[str] = set()
            for wb_code, tab_list in approved.items():
                for tab_name in tab_list:
                    key = f"{wb_code}:{tab_name}"
                    if key in seen_tabs:
                        errors.append(
                            f"Duplicate tab entry: {tab_name} in workbook {wb_code}"
                        )
                    seen_tabs.add(key)
        elif approved is not None:
            errors.append(
                f"approved_tabs must be a dict or None, got {type(approved).__name__}"
            )

        # 4. Decision record completeness
        for idx, decision in enumerate(self.decisions):
            if not decision.decision_id:
                errors.append(f"decision[{idx}] missing decision_id")
            if not decision.timestamp:
                errors.append(
                    f"decision[{idx}] ({decision.decision_id}) missing timestamp"
                )
            if not decision.phase:
                errors.append(f"decision[{idx}] ({decision.decision_id}) missing phase")

        return errors


# ---------------------------------------------------------------------------
# B. Artifact resolution helpers
# ---------------------------------------------------------------------------


def _resolve_artifacts(node: Any, base_dir: Path) -> Any:
    """Recursively resolve ``{"_artifact": "path"}`` dicts into inline data.

    Missing files are replaced with empty lists.

    Parameters
    ----------
    node : Any
        Data structure (dict, list, or scalar) to resolve.
    base_dir : Path
        Base directory for resolving relative artifact paths.

    Returns
    -------
    Any
        Resolved data with artifact references replaced by their contents.
    """
    if isinstance(node, dict):
        if set(node.keys()) == {"_artifact"}:
            artifact_path = base_dir / node["_artifact"]
            if artifact_path.exists():
                try:
                    loaded = json.loads(artifact_path.read_text(encoding="utf-8"))
                    return loaded
                except Exception as exc:
                    logger.warning(
                        "failed to load artifact %s: %s — using empty list",
                        artifact_path,
                        exc,
                    )
                    return []
            else:
                logger.warning(
                    "artifact not found: %s — using empty list", artifact_path
                )
                return []
        else:
            return {k: _resolve_artifacts(v, base_dir) for k, v in node.items()}
    elif isinstance(node, list):
        return [_resolve_artifacts(item, base_dir) for item in node]
    else:
        return node


def _write_contract_artifact(data: dict[str, Any], path: Path) -> None:
    """Write a contract dict as a JSON artifact file.

    Uses JSON for consistency with existing artifact patterns
    (broad_inventory, shortlist, etc. are all JSON).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("failed to write contract artifact %s: %s", path, exc)
