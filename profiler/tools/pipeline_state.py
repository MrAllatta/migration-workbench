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

        # Resolve _artifact references back into inline data
        base_dir = file_path.parent
        resolved = _resolve_artifacts(raw, base_dir)
        if not isinstance(resolved, dict):
            raise CommandError(
                f"Checkpoint at {file_path} resolved to non-dict."
            )

        return cls._from_resolved_dict(resolved)

    @classmethod
    def load_or_create(
        cls,
        config_path: str | Path,
        checkpoint_path: str | Path | None = None,
        *,
        domain_context: DomainContext | None = None,
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

        Returns
        -------
        PipelineState
        """
        if checkpoint_path is None:
            checkpoint_path = Path(str(config_path)).with_suffix(".yaml")
        checkpoint_path = Path(checkpoint_path)

        if checkpoint_path.exists():
            return cls.load(checkpoint_path)

        # Seed domain knowledge from DomainContext or config JSON
        if domain_context is not None:
            return cls(
                domain_knowledge=DomainKnowledge.from_domain_context(
                    domain_context
                )
            )

        state = cls()
        config_file = Path(config_path)
        if config_file.exists():
            try:
                config = json.loads(
                    config_file.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError):
                config = {}
            domain_val = config.get("domain")
            if domain_val:
                state.domain_knowledge.domain = str(domain_val)
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
        }

        discovery = self.discovery
        disc: dict[str, Any] = {}

        # Small fields inline (handle None defaults)
        disc["source_tree"] = discovery.source_tree or {}
        disc["workbook_index"] = discovery.workbook_index
        disc["approved_tabs"] = discovery.approved_tabs or {}

        # Large fields → external JSON (handle None defaults)
        for field_name in ("broad_inventory", "shortlist"):
            data = getattr(discovery, field_name)
            if data:
                artifact_path = base_dir / f"pipeline-state-{field_name}.json"
                artifact_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                disc[field_name] = {
                    "_artifact": str(artifact_path.relative_to(base_dir))
                }
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
            payload["schema_contract"] = {
                "_artifact": "build/schema-contract.yaml"
            }
        if self.interaction_contract:
            payload["interaction_contract"] = {
                "_artifact": "build/interaction-contract.yaml"
            }

        return payload

    @classmethod
    def _from_resolved_dict(
        cls, raw: dict[str, Any]
    ) -> PipelineState:
        """Reconstruct a PipelineState from a fully-resolved plain dict."""
        discovery_raw = raw.get("discovery") or {}
        domain_raw = raw.get("domain_knowledge") or {}
        deep_raw = raw.get("deep_profile_index") or {}

        discovery = DiscoveryState(
            source_tree=discovery_raw.get("source_tree") or {},
            workbook_index=list(
                discovery_raw.get("workbook_index") or []
            ),
            broad_inventory=list(
                discovery_raw.get("broad_inventory") or []
            ),
            shortlist=list(discovery_raw.get("shortlist") or []),
            approved_tabs=dict(
                discovery_raw.get("approved_tabs") or {}
            ),
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

        return cls(
            version=str(raw.get("version", "0.0.9")),
            discovery=discovery,
            deep_profile_index=deep_profile_index,
            domain_knowledge=domain_knowledge,
            schema_contract=None,  # Loaded from artifact on demand
            interaction_contract=None,
        )

    # ------------------------------------------------------------------
    # Phase methods with guard clauses
    # ------------------------------------------------------------------

    def discover(
        self, drive_service=None, sheets_service=None
    ) -> PipelineState:
        """Phase 0/1: Discover source tree and enumerate workbooks.

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
        self.discovery.source_tree = {}
        self.discovery.workbook_index = []
        self.discovery.broad_inventory = []
        self.discovery.shortlist = []
        return self

    def score_and_select(self) -> PipelineState:
        """Phase 1/2: Score and select tabs for deep profiling.

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
        self.discovery.approved_tabs = {}
        return self

    def deep_profile(self, sheets_service=None) -> PipelineState:
        """Phase 3: Deep-profile approved tabs.

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
        return self

    def derive_contracts(self) -> PipelineState:
        """Derive schema and interaction contracts from profile data.

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
        self.schema_contract = {}
        self.interaction_contract = {}
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
