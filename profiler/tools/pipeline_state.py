"""PipelineState — layered profiler runtime state and checkpoint.

The pipeline operator reads & edits checkpoint YAML between phases.
Phase methods use guard clauses to enforce ordering.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# A. Dataclass layer
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryState:
    """Mechanical findings from the profiler's discovery phase.

    Each field is small metadata — never raw grid data.
    """

    source_tree: dict | None = None
    workbook_index: list[dict] | None = None
    broad_inventory: list[dict] | None = None
    shortlist: list[dict] | None = None
    approved_tabs: dict[str, list[str]] | None = None


@dataclass
class DeepProfileIndex:
    """References to external deep-profile JSON artifacts."""

    entries: list[dict] = field(default_factory=list)


@dataclass
class DomainKnowledge:
    """Human-provided domain knowledge (evolved from DomainContext).

    Carries vocabulary, year scope, deduplication strategy, entity
    definitions, glossary, and operator scope notes.
    """

    domain: str = ""
    vocabulary: dict[str, list[str]] = field(default_factory=dict)
    year_scope: dict[str, list[int]] = field(default_factory=dict)
    deduplication: dict = field(default_factory=dict)
    entities: list[dict] = field(default_factory=list)
    glossary: dict[str, str] = field(default_factory=dict)
    scope_notes: str = ""

    # ------------------------------------------------------------------ #
    # B. DomainContext → DomainKnowledge bridge
    # ------------------------------------------------------------------ #

    @classmethod
    def from_domain_context(cls, ctx) -> DomainKnowledge:
        """Convert a ``DomainContext`` to ``DomainKnowledge``.

        Parameters
        ----------
        ctx : DomainContext
            Instance from ``profiler.tools.domain_context``.

        Returns
        -------
        DomainKnowledge
            Flat-dict representation of the same domain knowledge.
        """
        return cls(
            domain=str(ctx.domain) if ctx.domain else "",
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
                "strategy": str(ctx.deduplication.strategy),
                "exceptions": list(ctx.deduplication.exceptions),
            },
            entities=list(ctx.entities),
            glossary=dict(ctx.glossary),
            scope_notes=str(ctx.scope_notes) if ctx.scope_notes else "",
        )


@dataclass
class PipelineState:
    """Top-level runtime state object for the profiler pipeline.

    Three layers:
      1. Machine discoveries (``discovery``, ``deep_profile_index``)
      2. Human domain knowledge (``domain_knowledge``)
      3. Derived contracts    (``schema_contract``, ``interaction_contract``)
    """

    version: str = "0.1.0"
    discovery: DiscoveryState = field(default_factory=DiscoveryState)
    deep_profile_index: DeepProfileIndex = field(default_factory=DeepProfileIndex)
    domain_knowledge: DomainKnowledge = field(default_factory=DomainKnowledge)
    schema_contract: dict | None = None
    interaction_contract: dict | None = None

    # ------------------------------------------------------------------ #
    # C. Checkpoint I/O
    # ------------------------------------------------------------------ #

    def save_checkpoint(self, path: str | Path) -> None:
        """Serialize to YAML using ``asdict()``.

        Parameters
        ----------
        path : str | Path
            Filesystem path for the checkpoint YAML.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        with open(path, "w", encoding="utf-8") as fh:
            yaml.dump(
                data,
                fh,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )

    @classmethod
    def load(cls, path: str | Path) -> PipelineState:
        """Deserialize from a checkpoint YAML file.

        Parameters
        ----------
        path : str | Path
            Path to the checkpoint YAML.

        Returns
        -------
        PipelineState
            Reconstructed pipeline state.
        """
        path = Path(path)
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not isinstance(raw, dict):
            raise ValueError(f"Expected a YAML mapping in {path}")
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, raw: dict) -> PipelineState:
        """Build ``PipelineState`` from a deserialized YAML dict.

        Handles missing / ``None`` keys gracefully.
        """
        discovery_raw = raw.get("discovery") or {}
        discovery = DiscoveryState(
            source_tree=discovery_raw.get("source_tree"),
            workbook_index=discovery_raw.get("workbook_index") or [],
            broad_inventory=discovery_raw.get("broad_inventory") or [],
            shortlist=discovery_raw.get("shortlist") or [],
            approved_tabs=discovery_raw.get("approved_tabs"),
        )

        deep_raw = raw.get("deep_profile_index") or {}
        deep_profile_index = DeepProfileIndex(
            entries=deep_raw.get("entries") or [],
        )

        dk_raw = raw.get("domain_knowledge") or raw.get("domain") or {}
        domain_knowledge = DomainKnowledge(
            domain=str(dk_raw.get("domain", "")),
            vocabulary=dk_raw.get("vocabulary") or {},
            year_scope=dk_raw.get("year_scope") or {},
            deduplication=dk_raw.get("deduplication") or {},
            entities=dk_raw.get("entities") or [],
            glossary=dk_raw.get("glossary") or {},
            scope_notes=str(dk_raw.get("scope_notes", "")),
        )

        return cls(
            version=str(raw.get("version", "0.1.0")),
            discovery=discovery,
            deep_profile_index=deep_profile_index,
            domain_knowledge=domain_knowledge,
            schema_contract=raw.get("schema_contract"),
            interaction_contract=raw.get("interaction_contract"),
        )

    @classmethod
    def load_or_create(
        cls,
        config_path: str | Path,
        checkpoint_path: str | Path | None = None,
    ) -> PipelineState:
        """Load existing checkpoint or create fresh from config JSON.

        Parameters
        ----------
        config_path : str | Path
            Path to a JSON config file (e.g. ``cohort_corpus.json``).
        checkpoint_path : str | Path | None
            Path to an existing checkpoint YAML.  If ``None``, derived
            from ``config_path`` by replacing the suffix.

        Returns
        -------
        PipelineState
        """
        if checkpoint_path is None:
            checkpoint_path = Path(str(config_path)).with_suffix(".yaml")
        checkpoint_path = Path(checkpoint_path)

        if checkpoint_path.exists():
            return cls.load(checkpoint_path)

        # Fresh creation — read domain from config JSON if present
        state = cls()
        config_path = Path(config_path)
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                config = {}
            domain_val = config.get("domain")
            if domain_val:
                state.domain_knowledge.domain = str(domain_val)
        return state

    # ------------------------------------------------------------------ #
    # D. Phase methods with guard clauses
    # ------------------------------------------------------------------ #

    def discover(self, drive_service=None, sheets_service=None) -> PipelineState:
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
            raise RuntimeError("discover: source_tree already populated")
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
            raise RuntimeError("score_and_select: discover() must run first")
        if self.discovery.shortlist is None:
            raise RuntimeError("score_and_select: shortlist is None")
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
            raise RuntimeError("deep_profile: no approved_tabs")
        self.deep_profile_index = DeepProfileIndex()
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
            raise RuntimeError("derive_contracts: deep_profile must run first")
        self.schema_contract = {}
        self.interaction_contract = {}
        return self
