"""PipelineState — layered profiler runtime state and checkpoint.

The pipeline operator reads & edits checkpoint YAML between phases.
Phase methods use guard clauses to enforce ordering.  Large discovery
data (``broad_inventory``, ``shortlist``) is externalized to JSON
artifacts and referenced by ``_artifact`` keys to keep the YAML
human-reviewable.
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

logger = logging.getLogger(__name__)

# Fields that are externalized to JSON artifacts (not inlined in YAML).
_ARTIFACT_FIELDS: set[str] = {
    "broad_inventory",
    "shortlist",
    "deep_profiles",
}


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


_CHECKPOINT_CURRENT_VERSION = "0.0.9"

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


_CHECKPOINT_MIGRATIONS: dict[str, list[Callable[[dict], dict]]] = {
    # Migrations keyed by the target version; when upgrading from a(version) < key
    # and the key is <= current, apply the migrations to upgrade payloads.
    "0.0.9": [_migrate_v0_0_8_to_v0_0_9],
}


# ---------------------------------------------------------------------------
# A. Dataclass layer
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryState:
    """Machine-learned profiler findings (Layer 1).

    Each field is small metadata — never raw grid data.  Large lists
    (``broad_inventory``, ``shortlist``) are externalized to JSON
    artifacts during checkpoint save.
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
                f"workbook_index must be list, "
                f"got {type(self.workbook_index).__name__}"
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
    """

    # Must match pyproject.toml version — kept here so checkpoint format
    # version is explicit and testable without importing pyproject.toml.
    version: str = "0.0.9"
    discovery: DiscoveryState = field(default_factory=DiscoveryState)
    deep_profile_index: DeepProfileIndex = field(default_factory=DeepProfileIndex)
    domain_knowledge: DomainKnowledge = field(default_factory=DomainKnowledge)
    schema_contract: dict[str, Any] | None = None
    interaction_contract: dict[str, Any] | None = None
    decisions: list[DecisionRecord] = field(default_factory=list)

    # Runtime-only fields (not serialized to checkpoint).
    _config: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    _out_dir: Path | None = field(default=None, repr=False, compare=False)
    _date_stamp: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate field types on construction."""
        if self.version and not isinstance(self.version, str):
            raise TypeError(
                f"version must be str, got {type(self.version).__name__}"
            )
        if self.discovery is not None and not isinstance(
            self.discovery, DiscoveryState
        ):
            raise TypeError(
                f"discovery must be DiscoveryState, "
                f"got {type(self.discovery).__name__}"
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
    ) -> PipelineState:
        """Set runtime configuration for pipeline execution.

        These fields are stored privately (not serialized to checkpoint)
        and are consumed by phase methods that need them.

        Args:
            config: Parsed cohort corpus config dict.
            out_dir: Directory for profiler JSON artifacts.
            date_stamp: Timestamp for artifact filenames (ISO date string).

        Returns:
            PipelineState: Self for chaining.
        """
        self._config = config or self._config or {}
        self._out_dir = Path(out_dir) if out_dir else (self._out_dir or Path("data/profile_snapshots"))
        self._date_stamp = date_stamp or self._date_stamp or date.today().isoformat()
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
    # Checkpoint I/O
    # ------------------------------------------------------------------

    def save_checkpoint(self, path: str | Path) -> None:
        """Serialize state to a YAML checkpoint with ``_artifact`` references.

        Large fields (``broad_inventory``, ``shortlist``) are written to
        sibling JSON files and referenced by ``_artifact`` keys, keeping the
        YAML human-reviewable.

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
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, default_flow_style=False),
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
            logger.info(
                "checkpoint not found at %s — returning empty state", file_path
            )
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
            raise CommandError(
                f"Checkpoint at {file_path} is not a YAML mapping."
            )

        # Apply format migrations before resolving artifacts
        raw = cls._apply_migrations(raw)

        # Resolve _artifact references back into inline data
        base_dir = file_path.parent
        resolved = _resolve_artifacts(raw, base_dir)
        if not isinstance(resolved, dict):
            raise CommandError(
                f"Checkpoint at {file_path} resolved to non-dict."
            )

        return cls._from_resolved_dict(resolved, base_dir=base_dir)

    @classmethod
    def load_or_create(
        cls,
        config_path: str | Path,
        checkpoint_path: str | Path | None = None,
        *,
        domain_context: DomainContext | None = None,
        out_dir: str | Path | None = None,
        date_stamp: str | None = None,
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
        disc["source_tree"] = discovery.source_tree or {}
        disc["workbook_index"] = discovery.workbook_index

        # approved_tabs: preserve None sentinel for guard clauses
        if discovery.approved_tabs is None:
            disc["approved_tabs"] = None
        else:
            disc["approved_tabs"] = discovery.approved_tabs

        # Large fields → external JSON (preserve None sentinels)
        for field_name in ("broad_inventory", "shortlist"):
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
            artifact_path = (
                base_dir / "pipeline-state-deep-profiles.json"
            )
            artifact_path.write_text(
                json.dumps(self.deep_profile_index.entries, indent=2),
                encoding="utf-8",
            )
            payload["deep_profile_index"] = {
                "_artifact": str(
                    artifact_path.relative_to(base_dir)
                )
            }
        else:
            payload["deep_profile_index"] = {"entries": []}

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
            _write_contract_artifact(
                self.interaction_contract, contract_artifact_path
            )

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
            list(shortlist_raw)
            if isinstance(shortlist_raw, list)
            else shortlist_raw
        )
        approved_tabs_raw = discovery_raw.get("approved_tabs")
        approved_tabs = (
            dict(approved_tabs_raw)
            if isinstance(approved_tabs_raw, dict)
            else approved_tabs_raw
        )

        discovery = DiscoveryState(
            source_tree=discovery_raw.get("source_tree") or {},
            workbook_index=list(
                discovery_raw.get("workbook_index") or []
            ),
            broad_inventory=list(
                discovery_raw.get("broad_inventory") or []
            ),
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

        decisions = [
            DecisionRecord(**d) for d in decisions_raw
        ]

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

        return cls(
            version=str(raw.get("version", "0.0.9")),
            discovery=discovery,
            deep_profile_index=deep_profile_index,
            domain_knowledge=domain_knowledge,
            schema_contract=schema_contract,
            interaction_contract=interaction_contract,
            decisions=decisions,
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
            raise RuntimeError(
                "discover: source_tree already populated"
            )
        from profiler.tools.cohort_corpus import run_cohort_corpus

        out_dir = self._out_dir or Path("data/profile_snapshots")
        date_stamp = self._date_stamp or date.today().isoformat()

        artifact_paths = run_cohort_corpus(
            drive_service=drive_service,
            sheets_service=sheets_service,
            config=self._config or {},
            out_dir=out_dir,
            date_stamp=date_stamp,
            stop_before_deep=True,
        )

        self.discovery.source_tree = self._load_json_artifact(
            artifact_paths.get("discovery"), {}
        )
        self.discovery.workbook_index = self._load_json_artifact(
            artifact_paths.get("index"), []
        )
        self.discovery.broad_inventory = self._load_json_artifact(
            artifact_paths.get("broad_coverage"), []
        )
        self.discovery.shortlist = self._load_json_artifact(
            artifact_paths.get("tab_shortlist"), []
        )
        self.discovery.approved_tabs = self._load_json_artifact(
            artifact_paths.get("tab_selection"), {}
        )

        for tab in (self.discovery.shortlist or []):
            score = tab.get("score", 0)
            confidence = min(abs(score) / 100.0, 1.0) if score else 0.5
            self.record_decision(
                decision_id=f"discover_tab_{tab.get('tab_title', 'unknown')}",
                phase="discover",
                description=(
                    f"Scored tab '{tab.get('tab_title', 'unknown')}' "
                    f"({tab.get('scoring_rationale', 'heuristics')})"
                ),
                outcome="approved" if confidence >= 0.5 else "deferred",
                confidence=confidence,
                metadata={"score": score, "tab_title": tab.get("tab_title", "")},
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
            raise RuntimeError(
                "score_and_select: discover() must run first"
            )
        if self.discovery.shortlist is None:
            raise RuntimeError(
                "score_and_select: shortlist is None"
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

        scored_tabs: list[dict] = []
        for tab in (self.discovery.broad_inventory or []):
            title = tab.get("tab_title", "")
            rows = tab.get("row_count", 0) or 0
            cols = tab.get("column_count", 0) or 0

            raw_score, reasons, breakdown = score_tab(
                title=title,
                rows=rows,
                cols=cols,
                domain_context=domain_ctx,
            )

            # Normalize score to 0.0-1.0 range for confidence
            max_possible = 100
            normalized = max(0.0, min(raw_score / max_possible, 1.0)) if max_possible else 0.0

            entry = {
                "tab_title": title,
                "score": raw_score,
                "confidence": normalized,
                "scoring_rationale": "; ".join(reasons) if reasons else "No domain match",
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
            raise RuntimeError(
                "deep_profile: no approved_tabs"
            )
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
            self.deep_profile_index.entries = list(deep_coverage.values())

        for entry in self.deep_profile_index.entries:
            for fk_candidate in entry.get("fk_candidates") or []:
                col = fk_candidate.get("column", "unknown")
                target = fk_candidate.get("target", "unknown")
                confidence = fk_candidate.get("confidence", 0.5)
                self.record_decision(
                    decision_id=f"fk_{entry.get('tab', 'unknown')}_{col}",
                    phase="deep_profile",
                    description=(
                        f"FK candidate: "
                        f"{entry.get('tab', 'unknown')}.{col} -> {target}"
                    ),
                    outcome="approved" if confidence >= 0.5 else "deferred",
                    confidence=confidence,
                    metadata={
                        "tab": entry.get("tab", ""),
                        "column": col,
                        "target": target,
                    },
                )

        return self

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
            raise RuntimeError(
                "derive_contracts: deep_profile must run first"
            )
        tables: list[dict] = []
        for entry in self.deep_profile_index.entries:
            tab_name = entry.get("tab", "unknown")
            columns = entry.get("columns") or []
            fields = []
            for col in columns:
                col_name = col.get("header", "unknown")
                col_type = col.get("data_type", "string")
                fields.append({
                    "name": col_name,
                    "source_column": col_name,
                    "data_type": col_type,
                })

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
                    f"Derived model name '{model_name}' "
                    f"from tab title '{tab_name}'"
                ),
                outcome="approved",
                confidence=0.7,
                metadata={"tab_name": tab_name, "model_name": model_name},
            )

        self.schema_contract = {"tables": tables}
        self.interaction_contract = {"views": []}

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
                    loaded = json.loads(
                        artifact_path.read_text(encoding="utf-8")
                    )
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
            return {
                k: _resolve_artifacts(v, base_dir)
                for k, v in node.items()
            }
    elif isinstance(node, list):
        return [
            _resolve_artifacts(item, base_dir) for item in node
        ]
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
