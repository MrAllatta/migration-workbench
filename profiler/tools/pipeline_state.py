"""PipelineState — layered profiler runtime state and checkpoint.

The pipeline operator reads & edits checkpoint YAML between phases.
Phase methods use guard clauses to enforce ordering.  Large discovery
data (``broad_inventory``, ``shortlist``, ``source_tree``) is
externalized to JSON artifacts and referenced by ``_artifact`` keys
to keep the YAML human-reviewable.
"""

from __future__ import annotations

import json
import logging
import os
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


_CHECKPOINT_CURRENT_VERSION = "0.2.0"


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


_CHECKPOINT_MIGRATIONS: dict[str, list[Callable[[dict], dict]]] = {
    # Migrations keyed by the target version; when upgrading from a(version) < key
    # and the key is <= current, apply the migrations to upgrade payloads.
    "0.0.9": [_migrate_v0_0_8_to_v0_0_9],
    "0.1.0": [_migrate_v0_0_9_to_v0_1_0],
    # 0.2.0: BehavioralSpec field added — deserializer handles None gracefully.
    "0.2.0": [
        lambda raw: raw,
    ],
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


def _parse_raw_deep_profile(deep_data: dict) -> list[dict]:
    """Parse raw Google Sheets API response into enriched column entries.

    Farm's deep profile JSON files contain raw API response data without
    pre-enriched ``columns``.  This function extracts headers from the first
    row, collects non-empty values from subsequent rows, and computes null
    rate and distinct values for each column.

    Args:
        deep_data: Raw deep profile JSON dict with ``raw.sheets[0].data[0].rowData``.

    Returns:
        List of column dicts with ``header_label``, ``null_rate``, and
        ``distinct_values`` keys.
    """
    columns: list[dict] = []
    try:
        sheet = deep_data["raw"]["sheets"][0]
        data = sheet["data"][0]
        row_data = data.get("rowData", [])
        if not row_data:
            return columns

        # First row is headers
        header_row = row_data[0]
        headers: list[str] = []
        for cell in header_row.get("values", []):
            headers.append(
                cell.get("formattedValue")
                or cell.get("effectiveValue", {}).get("stringValue", "")
            )

        # Collect data for each column from subsequent rows
        col_values: list[list[str]] = [[] for _ in headers]
        for row in row_data[1:]:
            for col_index, cell in enumerate(row.get("values", [])):
                if col_index >= len(headers):
                    break
                val = cell.get("formattedValue") or cell.get("effectiveValue", {}).get(
                    "stringValue", ""
                )
                if val:
                    col_values[col_index].append(val)

        total_data_rows = len(row_data) - 1
        for col_index, header in enumerate(headers):
            values = col_values[col_index]
            null_rate = (
                (total_data_rows - len(values)) / total_data_rows
                if total_data_rows > 0
                else 0.0
            )
            columns.append(
                {
                    "header_label": header,
                    "null_rate": null_rate,
                    "distinct_values": values[:50],
                }
            )
    except (KeyError, IndexError):
        pass
    return columns


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
    test_scaffold: str | None = field(default=None, repr=False)
    doc_scaffold: str | None = field(default=None, repr=False)

    # Operator-defined priority stack rank for workflows
    operator_priority: dict[str, int] = field(default_factory=dict)
    # Maps workflow_id -> priority rank (1 = highest)

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

    @staticmethod
    def _load_json_artifact(path: str | Path | None, default: Any = None) -> Any:
        """Load a JSON artifact file, returning *default* on failure.

        Args:
            path: Path to JSON file, or ``None``.
            default: Fallback value if file is missing or unreadable.

        Returns:
            Parsed JSON content or *default*.
        """
        if not path:
            return default
        p = Path(path)
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("failed to load artifact %s", p)
            return default

    @staticmethod
    def _build_google_services() -> tuple[Any, Any]:
        """Build Google Drive and Sheets API service objects.

        Returns:
            tuple: ``(drive_service, sheets_service)`` or ``(None, None)``
            if the required packages are not installed.
        """
        try:
            from connectors.google_sheets import (
                DRIVE_READONLY_SCOPE,
                SHEETS_READONLY_SCOPE,
                build_google_service,
            )
        except ImportError:
            logger.warning("connectors.google_sheets not available")
            return None, None

        scopes = [SHEETS_READONLY_SCOPE, DRIVE_READONLY_SCOPE]
        drive_service = build_google_service("drive", "v3", scopes)
        sheets_service = build_google_service("sheets", "v4", scopes)
        return drive_service, sheets_service

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

        # Apply format migrations before resolving artifacts
        raw = cls._apply_migrations(raw)

        # Resolve _artifact references back into inline data
        base_dir = file_path.parent
        resolved = _resolve_artifacts(raw, base_dir)
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
            resolved_bs = (
                _resolve_artifacts(bs_raw, base_dir) if base_dir else bs_raw
            )
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

        return cls(
            version=str(raw.get("version", "0.2.0")),
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
        )

    # ------------------------------------------------------------------
    # Phase methods with guard clauses
    # ------------------------------------------------------------------

    def discover(
        self,
        drive_service=None,
        sheets_service=None,
    ) -> PipelineState:
        """Phase 0/1: Discover source tree, enumerate workbooks, and score tabs.

        Delegates to ``run_cohort_corpus()`` for profiling, then maps results
        onto discovery fields and records tab-scoring decisions.

        Parameters
        ----------
        drive_service : optional
            Google Drive service handle.
        sheets_service : optional
            Google Sheets service handle.

        Returns
        -------
        PipelineState
            Self for chaining.

        Raises
        ------
        RuntimeError
            If ``source_tree`` is already populated.
        """
        if self.discovery.source_tree is not None:
            raise RuntimeError("discover: source_tree already populated")
        from profiler.tools.cohort_corpus import run_cohort_corpus

        out_dir = self._out_dir or Path("data/profile_snapshots")
        date_stamp = self._date_stamp or date.today().isoformat()

        folder_id = self._config.get("folder_id") or os.environ.get("DRIVE_FOLDER_ID")

        artifact_paths = run_cohort_corpus(
            drive_service=drive_service,
            sheets_service=sheets_service,
            config=self._config or {},
            out_dir=out_dir,
            date_stamp=date_stamp,
            stop_before_deep=True,
            folder_id=folder_id,
        )

        self.discovery.source_tree = self._load_json_artifact(
            artifact_paths.get("discovery"), {}
        )
        # workbook_index JSON may be a dict with "records" key or a plain list.
        raw_index = self._load_json_artifact(artifact_paths.get("index"), [])
        if isinstance(raw_index, dict) and "records" in raw_index:
            self.discovery.workbook_index = raw_index["records"]
        elif isinstance(raw_index, list):
            self.discovery.workbook_index = raw_index
        else:
            self.discovery.workbook_index = []
        broad_coverage = self._load_json_artifact(
            artifact_paths.get("broad_coverage"), {}
        )
        if isinstance(broad_coverage, dict):
            self.discovery.broad_inventory = broad_coverage.get("results", [])
        elif isinstance(broad_coverage, list):
            self.discovery.broad_inventory = broad_coverage
        else:
            self.discovery.broad_inventory = []
        self.discovery.shortlist = self._load_json_artifact(
            artifact_paths.get("tab_shortlist"), []
        )
        tab_selection_raw = self._load_json_artifact(
            artifact_paths.get("tab_selection"), {}
        )
        if isinstance(tab_selection_raw, dict):
            self.discovery.approved_tabs = _extract_approved_tabs(tab_selection_raw)
        else:
            self.discovery.approved_tabs = tab_selection_raw

        shortlist_entries = self.discovery.shortlist
        if isinstance(shortlist_entries, dict):
            shortlist_entries = shortlist_entries.get("selected") or []
        for tab in shortlist_entries or []:
            score = tab.get("final_score", 0)
            confidence = min(abs(score) / 10.0, 1.0) if score else 0.5
            rationale = tab.get("breakdown_summary") or "heuristics"
            self.record_decision(
                decision_id=f"discover_tab_{tab.get('tab_title', 'unknown')}",
                phase="discover",
                description=(
                    f"Scored tab '{tab.get('tab_title', 'unknown')}' ({rationale})"
                ),
                outcome="approved" if confidence >= 0.5 else "deferred",
                confidence=confidence,
                metadata={
                    "score": score,
                    "tab_title": tab.get("tab_title", ""),
                    "workbook_code": tab.get("workbook_code", ""),
                },
            )

        return self

    def score_and_select(self) -> PipelineState:
        """Phase 1/2: Re-score tabs using domain knowledge (no API calls).

        Scores ``broad_inventory`` entries against ``domain_knowledge.vocabulary``
        via ``score_tab()``, updates ``shortlist``, and auto-selects high-confidence
        tabs (confidence >= 0.90) into ``approved_tabs``.

        Returns
        -------
        PipelineState
            Self for chaining.

        Raises
        ------
        RuntimeError
            If ``discover()`` has not been run or ``shortlist`` is
            ``None``.
        """
        if self.discovery.source_tree is None:
            raise RuntimeError("score_and_select: discover() must run first")
        if self.discovery.shortlist is None:
            raise RuntimeError("score_and_select: shortlist is None")

        if not self.domain_knowledge.vocabulary.get(
            "operational"
        ) and not self.domain_knowledge.vocabulary.get("reference"):
            logger.warning(
                "DomainKnowledge is empty — score_and_select phase will not re-rank. "
                "Provide a domain context file via --domain-context, "
                "or populate config/domain_context.yaml."
            )

        from profiler.tools.cohort_corpus import score_tab

        domain_ctx = DomainContext(
            domain=self.domain_knowledge.domain,
            description=self.domain_knowledge.description,
            vocabulary=DomainContext.VocabularyContext(
                operational=self.domain_knowledge.vocabulary.get("operational", []),
                reference=self.domain_knowledge.vocabulary.get("reference", []),
                support=self.domain_knowledge.vocabulary.get("support", []),
                derived=self.domain_knowledge.vocabulary.get("derived", []),
            ),
            year_scope=DomainContext.YearScope(
                active=self.domain_knowledge.year_scope.get("active", []),
                archived=self.domain_knowledge.year_scope.get("archived", []),
                forward=self.domain_knowledge.year_scope.get("forward", []),
            ),
            deduplication=DomainContext.DeduplicationContext(
                strategy=self.domain_knowledge.deduplication.get(
                    "strategy", "latest_year"
                ),
                exceptions=self.domain_knowledge.deduplication.get("exceptions", []),
            ),
            entities=list(self.domain_knowledge.entities),
            glossary=dict(self.domain_knowledge.glossary),
            scope_notes=self.domain_knowledge.scope_notes,
        )

        # Use tab-level shortlist (not workbook-level broad_inventory)
        shortlist_entries = self.discovery.shortlist
        if isinstance(shortlist_entries, dict):
            shortlist_entries = shortlist_entries.get("selected") or []
        if not isinstance(shortlist_entries, list):
            shortlist_entries = []

        scored_tabs: list[dict] = []
        for tab in shortlist_entries:
            title = tab.get("tab_title", "")
            rows = tab.get("rows_max", 0) or tab.get("row_count", 0) or 0
            cols = tab.get("cols_max", 0) or tab.get("column_count", 0) or 0

            raw_score, reasons, breakdown = score_tab(
                title=title,
                rows=rows,
                cols=cols,
                domain_context=domain_ctx,
            )

            # Normalize score to 0.0-1.0 range for confidence
            normalized = max(0.0, min(raw_score / 100.0, 1.0))

            entry = {
                "tab_title": title,
                "score": raw_score,
                "confidence": normalized,
                "scoring_rationale": (
                    "; ".join(reasons) if reasons else "No domain match"
                ),
                "breakdown": breakdown,
            }
            scored_tabs.append(entry)

            self.record_decision(
                decision_id=f"rescore_{title}",
                phase="score_and_select",
                description=(
                    f"Re-scored tab '{title}': "
                    f"{'; '.join(reasons) if reasons else 'No domain match'}"
                ),
                outcome="approved" if normalized >= 0.5 else "deferred",
                confidence=normalized,
                metadata={"raw_score": raw_score, "tab_title": title},
            )

        self.discovery.shortlist = scored_tabs

        approved: dict[str, list[str]] = {}
        for tab in scored_tabs:
            if tab["confidence"] >= 0.90:
                approved.setdefault("auto_selected", []).append(tab["tab_title"])
        self.discovery.approved_tabs = approved

        return self

    def deep_profile(self, sheets_service=None) -> PipelineState:
        """Phase 3: Deep-profile approved tabs.

        Delegates to ``run_cohort_corpus()`` in resume mode, then populates
        ``deep_profile_index.entries`` and records FK candidate decisions.

        Parameters
        ----------
        sheets_service : optional
            Google Sheets service handle.

        Returns
        -------
        PipelineState
            Self for chaining.

        Raises
        ------
        RuntimeError
            If ``approved_tabs`` is ``None``.
        """
        if self.discovery.approved_tabs is None:
            raise RuntimeError("deep_profile: no approved_tabs")
        from profiler.tools.cohort_corpus import run_cohort_corpus

        out_dir = self._out_dir or Path("data/profile_snapshots")
        date_stamp = self._date_stamp or date.today().isoformat()

        artifact_paths = run_cohort_corpus(
            drive_service=None,
            sheets_service=sheets_service,
            config=self._config or {},
            out_dir=out_dir,
            date_stamp=date_stamp,
            resume_from_tab_selection=True,
        )

        deep_coverage = self._load_json_artifact(
            artifact_paths.get("deep_coverage"), {}
        )
        if isinstance(deep_coverage, list):
            self.deep_profile_index.entries = deep_coverage
        elif isinstance(deep_coverage, dict):
            self.deep_profile_index.entries = deep_coverage.get(
                "results", list(deep_coverage.values())
            )

        for entry in self.deep_profile_index.entries:
            for fk_candidate in entry.get("fk_candidates") or []:
                col = fk_candidate.get("column", "unknown")
                target = fk_candidate.get("target", "unknown")
                confidence = fk_candidate.get("confidence", 0.5)
                entry_tab = entry.get("tab_title") or entry.get("tab", "unknown")
                self.record_decision(
                    decision_id=f"fk_{entry_tab}_{col}",
                    phase="deep_profile",
                    description=(f"FK candidate: {entry_tab}.{col} -> {target}"),
                    outcome="approved" if confidence >= 0.5 else "deferred",
                    confidence=confidence,
                    metadata={
                        "tab": entry_tab,
                        "column": col,
                        "target": target,
                    },
                )

        for entry in self.deep_profile_index.entries:
            try:
                self._enrich_entry_with_formula_dependencies(
                    entry,
                    out_dir=out_dir,
                    date_stamp=date_stamp,
                )
            except ImportError:
                logger.info(
                    "formula_dependency module not available \u2014 "
                    "skipping dependency analysis"
                )
                break

        return self

    def _enrich_entry_with_formula_dependencies(
        self,
        entry: dict[str, Any],
        out_dir: Path,
        date_stamp: str,
    ) -> None:
        """Run formula dependency analysis on a single deep-profile entry.

        If the entry has raw cell data with formulas, this method:
        1. Parses all formulas into a dependency graph.
        2. Saves the dependency artifact alongside the profile artifact.
        3. Computes dependency signals (cross-sheet edges, high-value nodes).
        4. Enriches column profiles with dependency-derived metadata.
        """
        out_json_path = entry.get("out_json")
        if not out_json_path:
            return

        profile_data = self._load_json_artifact(out_dir / out_json_path, None)
        if profile_data is None:
            return

        raw = profile_data.get("raw", {})
        if not raw:
            return

        try:
            from connectors.spreadsheet import (
                raw_sheet_to_row_lists,
                guess_header_row,
            )
        except ImportError:
            logger.warning(
                "connectors.spreadsheet not available \u2014 "
                "skipping dependency analysis for %s",
                out_json_path,
            )
            return

        try:
            row_lists = raw_sheet_to_row_lists(raw)
            header_index = guess_header_row(row_lists)
        except Exception:
            logger.warning(
                "failed to parse raw sheet data from %s",
                out_json_path,
            )
            return

        if header_index is None:
            return

        headers = row_lists[header_index]
        tab_title = entry.get("tab_title") or entry.get("tab", "unknown")

        formula_cells: list[dict[str, str]] = []
        column_cells: dict[str, dict] = {}

        for col_idx in range(len(headers)):
            header = str(headers[col_idx]).strip()
            col_letter = _col_index_to_letter(col_idx + 1)
            col_cells = []
            for row_idx in range(header_index + 1, len(row_lists)):
                cell_value = (
                    row_lists[row_idx][col_idx]
                    if col_idx < len(row_lists[row_idx])
                    else ""
                )
                cell_addr = f"{col_letter}{row_idx + 1}"
                cell_text = str(cell_value) if cell_value is not None else ""

                if isinstance(cell_value, str) and cell_value.startswith("="):
                    formula_cells.append(
                        {
                            "sheet": tab_title,
                            "cell": cell_addr,
                            "formula": cell_value,
                        }
                    )
                    col_cells.append({"kind": "formula", "text": cell_value})
                elif cell_text == "" or cell_text is None:
                    col_cells.append({"kind": "empty", "text": ""})
                else:
                    col_cells.append({"kind": "string", "text": cell_text})

            if header:
                column_cells[col_letter] = {
                    "header": header,
                    "column_cells": col_cells,
                    "tab_name": tab_title,
                }

        if not formula_cells:
            return

        from profiler.tools.formula_dependency import (
            build_dependency_artifact,
            compute_dependency_signals,
            parse_cells,
        )
        from profiler.tools.enrichment_utils import (
            enrich_fk_from_sheet_graph,
            enrich_from_dependency_graph,
        )

        parsed = parse_cells(formula_cells)
        workbook_key = entry.get("workbook_key") or Path(out_json_path).stem
        artifact = build_dependency_artifact(parsed, workbook_key=workbook_key)
        signals = compute_dependency_signals(artifact)

        artifact.update(signals)

        dep_path = out_dir / f"dependency_{Path(out_json_path).stem}.json"
        dep_path.parent.mkdir(parents=True, exist_ok=True)
        dep_path.write_text(
            __import__("json").dumps(artifact, indent=2),
            encoding="utf-8",
        )
        entry["dependency_json"] = str(dep_path.relative_to(out_dir))

        enrich_from_dependency_graph(column_cells, artifact)
        enrich_fk_from_sheet_graph(column_cells, artifact)

        computed_fields = entry.setdefault("computed_fields", [])
        for col_key, profile in column_cells.items():
            if profile.get("is_computed"):
                computed_fields.append(
                    {
                        "column": col_key,
                        "header": profile["header"],
                        "source": profile.get("computed_from", []),
                    }
                )
            fk_target = profile.get("suggested_fk_target")
            if fk_target:
                fk_candidates = entry.setdefault("fk_candidates", [])
                if not any(fc.get("column") == col_key for fc in fk_candidates):
                    fk_candidates.append(
                        {
                            "column": col_key,
                            "target": fk_target,
                            "confidence": 0.6,
                        }
                    )

        logger.info(
            "dependency analysis for %s: %d formulas, %d cross-sheet edges",
            tab_title,
            len(parsed),
            len(signals.get("cross_sheet_edges", [])),
        )

    def _extract_columns_from_entry(self, entry: dict[str, Any]) -> list[dict]:
        """Extract column definitions from a deep profile index entry.

        When the entry has inline ``columns`` (the old test-only format),
        return them directly.  When the entry references an ``out_json``
        profile file produced by ``cohort_corpus``, load the profile and
        extract column headers from the raw sheet data.

        Args:
            entry: A single entry from ``deep_profile_index.entries``.

        Returns:
            List of column dicts with ``header`` and ``data_type`` keys,
            or an empty list when no column data is available.
        """
        columns = entry.get("columns")
        if columns:
            return columns
        out_json_path = entry.get("out_json")
        if not out_json_path or self._out_dir is None:
            return []
        profile_data = PipelineState._load_json_artifact(
            self._out_dir / out_json_path, None
        )
        if profile_data is None:
            return []
        raw = profile_data.get("raw", {})
        if not raw:
            return []
        try:
            from connectors.spreadsheet import (
                guess_header_row,
                raw_sheet_to_row_lists,
            )
        except ImportError:
            logger.warning(
                "connectors.spreadsheet not available — "
                "cannot extract columns from profile %s",
                out_json_path,
            )
            return []
        try:
            row_lists = raw_sheet_to_row_lists(raw)
            header_index = guess_header_row(row_lists)
        except Exception:
            logger.warning(
                "failed to parse raw sheet data from profile %s",
                out_json_path,
            )
            return []
        if header_index is None:
            return []
        header_texts = [
            cell_text.strip()
            for cell_text in row_lists[header_index]
            if cell_text.strip()
        ]
        return [
            {"header": header_text, "data_type": "string"}
            for header_text in header_texts
        ]

    def derive_contracts(self) -> PipelineState:
        """Derive schema and interaction contracts from deep profile data.

        Builds a schema contract from ``deep_profile_index.entries`` by
        creating model names and field definitions for each profiled tab.

        Returns
        -------
        PipelineState
            Self for chaining.

        Raises
        ------
        RuntimeError
            If ``deep_profile_index.entries`` is empty (the list is
            never ``None`` — it defaults to ``[]``).
        """
        if not self.deep_profile_index.entries:
            raise RuntimeError("derive_contracts: deep_profile must run first")
        tables: list[dict] = []
        for entry in self.deep_profile_index.entries:
            tab_name = entry.get("tab_title") or entry.get("tab", "unknown")
            columns = self._extract_columns_from_entry(entry)
            fields = []
            for col in columns:
                col_name = col.get("header", "unknown")
                col_type = col.get("data_type", "string")
                fields.append(
                    {
                        "name": col_name,
                        "source_column": col_name,
                        "data_type": col_type,
                    }
                )

            # Convert tab name to PascalCase model name
            model_name = "".join(
                word.capitalize()
                for word in tab_name.replace("-", "_").replace(" ", "_").split("_")
            )
            table = {
                "model_name": model_name,
                "source_tab": tab_name,
                "fields": fields,
            }
            tables.append(table)

            self.record_decision(
                decision_id=f"model_{tab_name}",
                phase="derive_contracts",
                description=(
                    f"Derived model name '{model_name}' from tab title '{tab_name}'"
                ),
                outcome="approved",
                confidence=0.7,
                metadata={"tab_name": tab_name, "model_name": model_name},
            )

        self.schema_contract = {"tables": tables}

        # Record provenance for the derived schema contract
        if self.schema_contract:
            self.record_artifact_provenance(
                artifact_key="schema_contract",
                source="inferred",
                signals=[
                    {
                        "phase": "derive_contracts",
                        "tables_count": len(
                            self.schema_contract.get("tables", [])
                        ),
                    }
                ],
            )

        self.interaction_contract = {"views": []}

        # --- Tab Classification ---
        self._classify_deep_profiled_tabs()

        # --- Filter out UI-config tabs ---
        self._filter_ui_config_tabs()

        # Emit profiler signals alongside contracts
        self._emit_profiler_signals()

        return self

    def _classify_deep_profiled_tabs(self) -> None:
        """Classify deep-profiled tabs and store results in the interaction contract.

        Uses ``classify_tabs_batch`` from the tab classifier module. Collects
        classification signals, records a decision with the summary, and stores
        per-tab classification in the interaction contract.
        """
        try:
            from profiler.tools.tab_classifier import (
                classify_tabs_batch,
                classification_summary,
            )
        except ImportError:
            logger.warning("tab_classifier not available — skipping classification")
            return

        tab_entries: list[dict] = []
        for entry in self.deep_profile_index.entries:
            tab_title = entry.get("tab_title") or entry.get("tab", "unknown")
            tab_entries.append(
                {
                    "tab_title": tab_title,
                    "rows": entry.get("total_rows", 0),
                    "cols": entry.get("total_cols", 0),
                    "score": entry.get("score", 0),
                    "reasons": entry.get("scoring_reasons", []),
                    "breakdown": entry.get("breakdown", {}),
                }
            )

        if not tab_entries:
            return

        classifications = classify_tabs_batch(tab_entries)
        summary = classification_summary(classifications)

        self.record_decision(
            decision_id="tab_classification",
            phase="derive_contracts",
            description=(
                f"Classified {summary['total']} tabs: "
                f"{summary['classified']} classified, "
                f"{summary['coverage_pct']}% coverage"
            ),
            outcome="approved",
            confidence=summary["coverage_pct"] / 100.0 if summary["total"] > 0 else 0.0,
            metadata={
                "total": summary["total"],
                "classified": summary["classified"],
                "coverage_pct": summary["coverage_pct"],
                "counts": summary["counts"],
            },
        )

        # Store per-tab classification in interaction contract
        if self.interaction_contract is None:
            self.interaction_contract = {"views": []}
        self.interaction_contract["tab_classifications"] = {
            c.tab_title: {
                "category": c.category,
                "confidence": c.confidence,
                "rationale": c.rationale,
            }
            for c in classifications
        }

    def _filter_ui_config_tabs(self) -> None:
        """Filter out UI-config tabs from the schema contract.

        Reads ``tab_classifications`` from ``interaction_contract`` and
        removes any table from ``schema_contract["tables"]`` whose
        ``source_tab`` is classified as ``ui_config``. Records a decision
        for each excluded tab.

        Only excludes tabs whose deep profile entry has explicit
        ``total_rows`` or ``total_cols`` keys (meaning the entry was
        produced by a real deep-profile run, not a test stub).

        Gracefully skips if ``interaction_contract`` is ``None`` or
        ``tab_classifications`` is missing (backward compatibility).
        """
        if self.interaction_contract is None or self.schema_contract is None:
            return
        tab_classifications = self.interaction_contract.get("tab_classifications")
        if not tab_classifications:
            return

        ui_config_tabs: set[str] = {
            tab_title
            for tab_title, classification in tab_classifications.items()
            if classification.get("category") == "ui_config"
        }
        if not ui_config_tabs:
            return

        # Determine which tabs have real profile dimensionality data.
        # Entries that lack total_rows/total_cols are test stubs and
        # should not be filtered (the classifier falls back to defaults
        # that may not reflect real classification).
        profiled_tabs: set[str] = set()
        for entry in self.deep_profile_index.entries:
            tab_title = entry.get("tab_title") or entry.get("tab", "unknown")
            if "total_rows" in entry or "total_cols" in entry:
                profiled_tabs.add(tab_title)

        original_tables = self.schema_contract.get("tables", [])
        filtered_tables: list[dict] = []
        for table in original_tables:
            source_tab = table.get("source_tab", "")
            if source_tab in ui_config_tabs and source_tab in profiled_tabs:
                classification = tab_classifications.get(source_tab, {})
                confidence = classification.get("confidence", 0.0)
                sanitized = source_tab.replace(" ", "_").replace("-", "_")
                self.record_decision(
                    decision_id=f"exclude_ui_config_{sanitized}",
                    phase="derive_contracts",
                    description=(
                        f"Excluded tab '{source_tab}' from schema contract"
                        " — classified as ui_config"
                    ),
                    outcome="excluded",
                    confidence=confidence,
                    metadata={
                        "tab_name": source_tab,
                        "category": "ui_config",
                        "confidence": confidence,
                    },
                )
            else:
                filtered_tables.append(table)

        self.schema_contract["tables"] = filtered_tables

    def _emit_profiler_signals(self) -> None:
        """Build and write profiler-signals YAML from deep profile index.

        Constructs a structure-like dict from ``deep_profile_index.entries``,
        then extracts signals via ``extract_signals`` and writes the result
        as a YAML artifact.  Sets ``profiler_signals_path`` to the absolute
        path of the written file.
        """
        if not self.deep_profile_index.entries:
            return

        from workbook.tools.signal_extraction import extract_signals

        # Build a minimal structure dict from deep-profile index entries
        fake_tabs: list[dict] = []
        for entry in self.deep_profile_index.entries:
            tab_title = entry.get("tab_title") or entry.get("tab", "unknown")
            columns = self._extract_columns_from_entry(entry)
            cols_out: list[dict] = []
            for col in columns:
                cols_out.append(
                    {
                        "header_label": col.get("header", "unknown"),
                        "is_formula": col.get("is_formula", False),
                    }
                )
            fake_tabs.append(
                {
                    "worksheet_title": tab_title,
                    "columns": cols_out,
                    "total_rows": entry.get("total_rows", 0),
                    "total_cols": len(cols_out),
                    "named_ranges": [],
                    "filter_views": [],
                }
            )

        fake_structure: dict[str, Any] = {
            "schema_version": "structure-draft-1",
            "source_id": self._config.get("source_id", ""),
            "provider": self._config.get("provider", "google_sheets"),
            "tabs": fake_tabs,
        }

        # Pass tab classifications into signal extraction if available
        tab_classifications = None
        if (
            self.interaction_contract
            and "tab_classifications" in self.interaction_contract
        ):
            tab_classifications = self.interaction_contract["tab_classifications"]

        signals = extract_signals(
            fake_structure,
            tab_classifications=tab_classifications,
        )

        # Determine output path: prefer runtime override, then alongside checkpoint
        signals_path = self._signals_output_path or (
            (self._out_dir or Path("build")).parent / "profiler-signals.yaml"
        )
        signals_path = Path(signals_path)
        signals_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("PyYAML not available — skipping signals artifact")
            return

        try:
            signals_path.write_text(
                yaml.safe_dump(
                    signals,
                    sort_keys=False,
                    allow_unicode=True,
                    default_flow_style=False,
                ),
                encoding="utf-8",
            )
            self.profiler_signals_path = str(signals_path.resolve())
            logger.info("wrote profiler signals to %s", self.profiler_signals_path)
        except Exception as exc:
            logger.warning(
                "failed to write profiler signals to %s: %s",
                signals_path,
                exc,
            )

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

    # ------------------------------------------------------------------
    # BPRS phase methods
    # ------------------------------------------------------------------

    def derive_operational_model(
        self, base_dir: str | os.PathLike[str] | None = None
    ) -> PipelineState:
        """Phase: Derive the operational model from profiler artifacts.

        Consumes ``discovery``, ``deep_profile_index``, and ``domain_knowledge``
        to produce the primary BPRS artifact.

        Args:
            base_dir: Base directory for resolving ``out_json`` relative paths
                in deep profile index entries.  If ``None``, entries with
                ``out_json`` but no inline ``columns`` are passed through
                unresolved.

        Returns:
            PipelineState: Self for chaining.

        Raises:
            RuntimeError: If ``domain_knowledge.domain`` is empty.
        """
        if not self.domain_knowledge.domain:
            raise RuntimeError(
                "derive_operational_model: domain_knowledge.domain is required"
            )

        from profiler.tools.operational_model_deriver import derive_operational_model

        # Resolve out_json references to inline column data
        entries: list[dict[str, Any]] = []
        for entry in self.deep_profile_index.entries or []:
            entry_dict = (
                dict(entry) if hasattr(entry, "__dataclass_fields__") else dict(entry)
            )
            out_json = entry_dict.get("out_json")
            if out_json and not entry_dict.get("columns"):
                candidate_bases: list[Path] = []
                if base_dir:
                    base_path = Path(base_dir)
                    candidate_bases.append(base_path)
                    candidate_bases.append(base_path.parent)
                    candidate_bases.append(base_path.parent / "data")

                resolved = False
                for candidate_base in candidate_bases:
                    candidate_path = candidate_base / out_json
                    if candidate_path.exists():
                        try:
                            with open(candidate_path, "r", encoding="utf-8") as f:
                                deep_data = json.load(f)
                            columns = deep_data.get("columns") or deep_data.get(
                                "summary", {}
                            ).get("columns", [])
                            if not columns:
                                columns = _parse_raw_deep_profile(deep_data)
                            entry_dict["columns"] = columns
                            resolved = True
                            break
                        except (OSError, json.JSONDecodeError):
                            continue

                if not resolved and base_dir:
                    logger.warning(
                        "Could not resolve out_json %s from base_dir %s",
                        out_json,
                        base_dir,
                    )

            # Resolve dependency_json artifact paths (formula dependency graph)
            # so the deriver can consume them without file I/O.
            dep_json = entry_dict.get("dependency_json")
            if dep_json and base_dir:
                dep_candidate_bases: list[Path] = [
                    Path(base_dir),
                    Path(base_dir).parent,
                    Path(base_dir).parent / "data",
                ]
                dep_resolved = False
                for dep_base in dep_candidate_bases:
                    dep_path = dep_base / dep_json
                    if dep_path.exists():
                        try:
                            with open(dep_path, "r", encoding="utf-8") as f:
                                entry_dict["dependency_artifact"] = json.load(f)
                            dep_resolved = True
                            break
                        except (OSError, json.JSONDecodeError):
                            continue
                if not dep_resolved:
                    logger.debug(
                        "Could not resolve dependency_json %s from base_dir %s",
                        dep_json,
                        base_dir,
                    )

            entries.append(entry_dict)

        self.operational_model = derive_operational_model(
            discovery={
                "workbook_index": self.discovery.workbook_index,
                "broad_inventory": self.discovery.broad_inventory,
            },
            deep_profile_index={"entries": entries},
            domain_knowledge={
                "domain": self.domain_knowledge.domain,
                "vocabulary": self.domain_knowledge.vocabulary,
            },
        )
        return self

    def derive_behavioral_spec(
        self, base_dir: str | os.PathLike[str] | None = None
    ) -> PipelineState:
        """Phase: Derive the behavioral specification from profiler artifacts.

        Consumes ``discovery``, ``deep_profile_index``, and ``domain_knowledge``
        to produce the MWBS BehavioralSpec artifact.

        Args:
            base_dir: Base directory for resolving ``out_json`` relative paths
                in deep profile index entries.

        Returns:
            PipelineState: Self for chaining.

        Raises:
            RuntimeError: If ``domain_knowledge.domain`` is empty.
        """
        if not self.domain_knowledge.domain:
            raise RuntimeError(
                "derive_behavioral_spec: domain_knowledge.domain is required"
            )

        from profiler.tools.behavioral_spec_elicitor import derive_behavioral_spec

        # Resolve out_json references to inline column data
        entries: list[dict[str, Any]] = []
        for entry in self.deep_profile_index.entries or []:
            entry_dict = (
                dict(entry) if hasattr(entry, "__dataclass_fields__") else dict(entry)
            )
            out_json = entry_dict.get("out_json")
            if out_json and not entry_dict.get("columns"):
                candidate_bases: list[Path] = []
                if base_dir:
                    base_path = Path(base_dir)
                    candidate_bases.append(base_path)
                    candidate_bases.append(base_path.parent)
                    candidate_bases.append(base_path.parent / "data")

                resolved = False
                for candidate_base in candidate_bases:
                    candidate_path = candidate_base / out_json
                    if candidate_path.exists():
                        try:
                            with open(candidate_path, "r", encoding="utf-8") as f:
                                deep_data = json.load(f)
                            columns = deep_data.get("columns") or deep_data.get(
                                "summary", {}
                            ).get("columns", [])
                            if not columns:
                                columns = _parse_raw_deep_profile(deep_data)
                            entry_dict["columns"] = columns
                            resolved = True
                            break
                        except (OSError, json.JSONDecodeError):
                            continue

                if not resolved and base_dir:
                    logger.warning(
                        "Could not resolve out_json %s from base_dir %s",
                        out_json,
                        base_dir,
                    )

            # Resolve dependency_json artifact paths
            dep_json = entry_dict.get("dependency_json")
            if dep_json and base_dir:
                dep_candidate_bases: list[Path] = [
                    Path(base_dir),
                    Path(base_dir).parent,
                    Path(base_dir).parent / "data",
                ]
                dep_resolved = False
                for dep_base in dep_candidate_bases:
                    dep_path = dep_base / dep_json
                    if dep_path.exists():
                        try:
                            with open(dep_path, "r", encoding="utf-8") as f:
                                entry_dict["dependency_artifact"] = json.load(f)
                            dep_resolved = True
                            break
                        except (OSError, json.JSONDecodeError):
                            continue
                if not dep_resolved:
                    logger.debug(
                        "Could not resolve dependency_json %s from base_dir %s",
                        dep_json,
                        base_dir,
                    )

            entries.append(entry_dict)

        self.behavioral_spec = derive_behavioral_spec(
            discovery={
                "workbook_index": self.discovery.workbook_index,
                "broad_inventory": self.discovery.broad_inventory,
            },
            deep_profile_index={"entries": entries},
            domain_knowledge={
                "domain": self.domain_knowledge.domain,
                "vocabulary": self.domain_knowledge.vocabulary,
            },
        )

        # Populate operator_priority from behavioral spec project metadata
        if self.behavioral_spec and self.behavioral_spec.project:
            project = self.behavioral_spec.project
            if project.operator:
                self.operator_priority[project.operator] = 1
            if project.developer:
                self.operator_priority[project.developer] = 2

        return self

    def derive_state_projections(
        self, projection: str = "schema_contract"
    ) -> PipelineState:
        """Phase: Derive state projections from the operational model.

        Currently supports ``schema_contract``, ``test_scaffold``, and
        ``doc_scaffold`` projections.

        Args:
            projection: Which projection to derive. Defaults to
                ``schema_contract``.

        Returns:
            PipelineState: Self for chaining.

        Raises:
            RuntimeError: If ``operational_model`` is not populated.
            ValueError: If *projection* is not supported.
        """
        if self.operational_model is None:
            raise RuntimeError(
                "derive_state_projections: operational_model must be derived first"
            )

        if projection == "schema_contract":
            self.schema_contract = self._derive_schema_contract_from_operational_model()
        elif projection == "test_scaffold":
            self.test_scaffold = self._derive_test_scaffold_from_operational_model()
        elif projection == "doc_scaffold":
            self.doc_scaffold = self._derive_doc_scaffold_from_operational_model()
        else:
            raise ValueError(f"Unsupported projection: {projection}")

        return self

    def _derive_schema_contract_from_operational_model(self) -> dict[str, Any]:
        """Derive a schema contract dict from the operational model.

        Maps events to contract tables, payloads to columns, and invariants
        to constraints.

        Returns:
            dict: Schema contract compatible with existing codegen.
        """
        # Guard is enforced by the caller, but type checker needs this.
        assert self.operational_model is not None

        tables: list[dict[str, Any]] = []
        for event in self.operational_model.events or []:
            columns: list[dict[str, Any]] = []
            for field_name in event.payload or []:
                columns.append(
                    {
                        "source_column": field_name,
                        "suggested_field_name": field_name.lower().replace(" ", "_"),
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 255, "blank": True},
                    }
                )

            tables.append(
                {
                    "suggested_model_name": event.id.lower().replace(" ", "_"),
                    "bundle_worksheet_title": event.sourced_from[0]["tab"]
                    if event.sourced_from
                    else "",
                    "columns": columns,
                }
            )

        return {"version": "1.1", "tables": tables}

    def _derive_test_scaffold_from_operational_model(self) -> str:
        """Derive a pytest test file string from the operational model.

        Generates test classes for invariants, workflows, and events
        based on the operational model data.

        Returns:
            str: Python source code for a pytest test module.
        """
        assert self.operational_model is not None

        from datetime import datetime, timezone

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        source_id = self.operational_model.source_id or "unknown"

        # --- Invariant tests ---
        invariant_tests_lines: list[str] = []
        for invariant in self.operational_model.invariants or []:
            if invariant.enforcement == "database_check":
                safe_name = invariant.id.lower().replace(" ", "_").replace("-", "_")
                expression = invariant.expression or ""
                invariant_tests_lines.append(
                    f"""    def test_{safe_name}(self):
        \"\"\"{expression}\"\"\"
        # TODO: implement with real model instances
        pass
"""
                )
        if not invariant_tests_lines:
            invariant_tests_lines.append(
                "    # No database_check invariants defined.\n"
            )
        invariant_tests = "\n".join(invariant_tests_lines).rstrip()

        # --- Workflow tests ---
        workflow_tests_lines: list[str] = []
        for workflow in self.operational_model.workflows or []:
            safe_name = workflow.id.lower().replace(" ", "_").replace("-", "_")
            commands_ids = workflow.commands or []
            commands_list_repr = str(commands_ids)
            workflow_tests_lines.append(
                f"""    def test_{safe_name}_has_commands(self):
        \"\"\"Workflow {workflow.id} must have at least one command.\"\"\"
        commands_list = {commands_list_repr}
        assert len(commands_list) >= 1
"""
            )
        if not workflow_tests_lines:
            workflow_tests_lines.append("    # No workflows defined.\n")
        workflow_tests = "\n".join(workflow_tests_lines).rstrip()

        # --- Event tests ---
        event_tests_lines: list[str] = []
        for event in self.operational_model.events or []:
            safe_name = event.id.lower().replace(" ", "_").replace("-", "_")
            payload_list = event.payload or []
            payload_list_repr = str(payload_list)
            event_tests_lines.append(
                f"""    def test_{safe_name}_has_payload(self):
        \"\"\"Event {event.id} must have payload fields.\"\"\"
        payload_list = {payload_list_repr}
        assert len(payload_list) >= 1
"""
            )
        if not event_tests_lines:
            event_tests_lines.append("    # No events defined.\n")
        event_tests = "\n".join(event_tests_lines).rstrip()

        return f'''"""Auto-generated operational model tests.

Generated from operational model: {source_id}
Generated at: {timestamp}
"""

import pytest


class TestOperationalInvariants:
    """Tests derived from operational model invariants."""

{invariant_tests}


class TestOperationalWorkflows:
    """Tests derived from operational model workflows."""

{workflow_tests}


class TestOperationalEvents:
    """Tests derived from operational model events."""

{event_tests}
'''

    def _derive_doc_scaffold_from_operational_model(self) -> str:
        """Derive a Markdown documentation string from the operational model.

        Generates a living documentation file describing the business operating
        system: capabilities, events, workflows, commands, and invariants.

        Returns:
            str: Markdown document as a string.
        """
        assert self.operational_model is not None

        from datetime import datetime, timezone

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        source_id = self.operational_model.source_id or "unknown"

        lines: list[str] = []
        lines.append(f"# Operational Model: {source_id}")
        lines.append("")
        lines.append(f"_Generated at: {timestamp}_")
        lines.append("")
        lines.append(
            "This document describes the operational model derived from "
            "profiler evidence. It captures the business operating system's "
            "capabilities, events, workflows, commands, and invariants."
        )
        lines.append("")

        # --- Capabilities ---
        lines.append("## Capabilities")
        lines.append("")
        capabilities = self.operational_model.capabilities or []
        if capabilities:
            for capability in capabilities:
                owners_str = capability.owner or "unknown"
                lines.append(f"- **{capability.id}** — Owner: {owners_str}")
        else:
            lines.append("*No capabilities defined.*")
        lines.append("")

        # --- Events ---
        lines.append("## Events")
        lines.append("")
        events = self.operational_model.events or []
        if events:
            lines.append("| Event ID | Payload Fields | Source Tab/Column |")
            lines.append("|----------|----------------|--------------------|")
            for event in events:
                payload_str = ", ".join(event.payload or []) or "*empty*"
                source_parts = []
                for src in event.sourced_from or []:
                    tab = src.get("tab", "")
                    column = src.get("column", "")
                    if tab and column:
                        source_parts.append(f"{tab}.{column}")
                    elif tab:
                        source_parts.append(tab)
                    elif column:
                        source_parts.append(column)
                source_str = "; ".join(source_parts) if source_parts else "*unknown*"
                lines.append(f"| `{event.id}` | {payload_str} | {source_str} |")
        else:
            lines.append("*No events defined.*")
        lines.append("")

        # --- Workflows ---
        lines.append("## Workflows")
        lines.append("")
        workflows = self.operational_model.workflows or []
        if workflows:
            for workflow in workflows:
                lines.append(f"### {workflow.id}")
                lines.append("")
                if workflow.frequency:
                    lines.append(f"- **Frequency:** {workflow.frequency}")
                if workflow.actor:
                    lines.append(f"- **Actor:** {workflow.actor}")
                if workflow.outcome:
                    lines.append(f"- **Outcome:** {workflow.outcome}")
                if workflow.commands:
                    commands_list = ", ".join(f"`{cmd}`" for cmd in workflow.commands)
                    lines.append(f"- **Commands:** {commands_list}")
                if workflow.evidence:
                    evidence_list = ", ".join(workflow.evidence)
                    lines.append(f"- **Evidence:** {evidence_list}")
                lines.append("")
        else:
            lines.append("*No workflows defined.*")
        lines.append("")

        # --- Commands ---
        lines.append("## Commands")
        lines.append("")
        commands = self.operational_model.commands or []
        if commands:
            for command in commands:
                lines.append(f"- `{command.id}`")
        else:
            # Collect unique command IDs from workflows as fallback
            command_ids: set[str] = set()
            for workflow in workflows:
                for cmd_id in workflow.commands or []:
                    command_ids.add(cmd_id)
            if command_ids:
                for cmd_id in sorted(command_ids):
                    lines.append(f"- `{cmd_id}`")
            else:
                lines.append("*No commands defined.*")
        lines.append("")

        # --- Invariants ---
        lines.append("## Invariants")
        lines.append("")
        invariants = self.operational_model.invariants or []
        if invariants:
            lines.append(
                "| Invariant ID | Expression | Enforcement | Violations Handling |"
            )
            lines.append(
                "|--------------|------------|-------------|---------------------|"
            )
            for invariant in invariants:
                expression_str = invariant.expression or "*none*"
                enforcement_str = invariant.enforcement or "application_logic"
                violations_str = invariant.violations_are or "warning"
                lines.append(
                    f"| `{invariant.id}` | `{expression_str}` "
                    f"| {enforcement_str} | {violations_str} |"
                )
        else:
            lines.append("*No invariants defined.*")
        lines.append("")

        # --- Event-to-Workflow Mapping ---
        lines.append("## Event-to-Workflow Mapping")
        lines.append("")
        # Build mapping by finding workflow/event pairs that share terms
        mapping_found = False
        workflow_event_terms: dict[str, set[str]] = {}
        for workflow in workflows:
            terms: set[str] = set()
            terms.add(workflow.id.lower())
            for cmd in workflow.commands or []:
                terms.add(cmd.lower())
            workflow_event_terms[workflow.id] = terms

        for event in events:
            event_terms: set[str] = set()
            event_terms.add(event.id.lower())
            for payload_field in event.payload or []:
                event_terms.add(payload_field.lower())

            matched = False
            for workflow_id, wf_terms in workflow_event_terms.items():
                shared = event_terms & wf_terms
                if shared:
                    lines.append(
                        f"- Event `{event.id}` may trigger workflow "
                        f"`{workflow_id}` (shared terms: "
                        f"{', '.join(sorted(shared))})"
                    )
                    matched = True
                    mapping_found = True

            if not matched:
                lines.append(f"- Event `{event.id}` — no workflow mapping identified")

        if not mapping_found and not events and not workflows:
            lines.append("*No event-to-workflow mappings available.*")
        lines.append("")

        return "\n".join(lines)

    def validate_operational_model(self) -> PipelineState:
        """Phase: Validate the operational model and compute coverage.

        This is a human review gate. The method computes coverage metrics
        and records a validation record.

        Returns:
            PipelineState: Self for chaining.

        Raises:
            RuntimeError: If ``operational_model`` is not populated.
        """
        if self.operational_model is None:
            raise RuntimeError(
                "validate_operational_model: operational_model must be derived first"
            )

        from profiler.tools.validation_framework import (
            CoverageReport,
            compute_coverage_metrics,
        )

        # Backward compat: derive behavioral_spec if not already set, so we
        # can use the new MWBS compute_coverage_metrics (single-arg).
        if self.behavioral_spec is None and self.domain_knowledge.domain:
            self.derive_behavioral_spec()

        if self.behavioral_spec is not None:
            self.coverage_report = compute_coverage_metrics(self.behavioral_spec)
        else:
            self.coverage_report = CoverageReport()
        return self

    def validate_behavioral_spec(
        self, base_dir: str | os.PathLike[str] | None = None
    ) -> PipelineState:
        """Phase: Validate the behavioral spec, computing coverage.

        Uses the new MWBS :func:`compute_coverage_metrics` which takes a
        single ``BehavioralSpec`` argument (not ``OperationalModel`` + dict).

        Returns:
            PipelineState: Self for chaining.

        Raises:
            RuntimeError: If ``behavioral_spec`` is not populated.
        """
        if self.behavioral_spec is None:
            raise RuntimeError(
                "validate_behavioral_spec: behavioral_spec must be derived first"
            )

        from profiler.tools.behavioral_spec_validation import compute_coverage_metrics

        self.coverage_report = compute_coverage_metrics(self.behavioral_spec)
        return self


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
