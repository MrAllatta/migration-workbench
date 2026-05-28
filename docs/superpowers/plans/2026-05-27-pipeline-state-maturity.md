# PipelineState Maturity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take PipelineState from structured checkpoint container to live pipeline orchestrator by implementing P0+P1 maturity gaps.

**Architecture:** Phase methods delegate to existing profiler tools (`run_cohort_corpus`, scoring helpers) but PipelineState coordinates the orchestration and records every autonomous decision with confidence scores. A flat `DecisionRecord` list on PipelineState provides the judgment taxonomy surface. Checkpoint I/O gains version migration and proper contract artifact resolution.

**Tech Stack:** Python 3.12, Django management commands, PyYAML, existing `profiler.tools.cohort_corpus`

---

## File Map

| File | Change | Responsibility |
|------|--------|---------------|
| `profiler/tools/pipeline_state.py` | Major additions | DecisionRecord, post-init validation, version migration, config routing, phase method rewrites, artifact path fix, contract resolution |
| `profiler/management/commands/run_pipeline_state.py` | Moderate refactor | Thin CLI wrapper — calls `state.phase_method()` instead of orchestrating |
| `profiler/tests/test_pipeline_state.py` | Add test classes | DecisionRecord, migration, validation, contract resolution, artifact path |
| `profiler/tests/test_run_pipeline_state_command.py` | Minor updates | Adapt to simplified command |

---

### Task 1: Post-Init Validation

Add lightweight `__post_init__` to all dataclasses. Independent of other changes.

**Files:**
- Modify: `profiler/tools/pipeline_state.py`
- Test: `profiler/tests/test_pipeline_state.py`

- [ ] **Step 1: Add `__post_init__` to `DomainKnowledge`**

```python
@dataclass
class DomainKnowledge:
    ...
    def __post_init__(self) -> None:
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
```

- [ ] **Step 2: Add `__post_init__` to `DiscoveryState`**

```python
@dataclass
class DiscoveryState:
    ...
    def __post_init__(self) -> None:
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
```

- [ ] **Step 3: Add `__post_init__` to `PipelineState`**

```python
@dataclass
class PipelineState:
    ...
    def __post_init__(self) -> None:
        if self.version and not isinstance(self.version, str):
            raise TypeError(
                f"version must be str, got {type(self.version).__name__}"
            )
        if self.discovery is not None and not isinstance(self.discovery, DiscoveryState):
            raise TypeError(
                f"discovery must be DiscoveryState, "
                f"got {type(self.discovery).__name__}"
            )
        if self.domain_knowledge is not None and not isinstance(self.domain_knowledge, DomainKnowledge):
            raise TypeError(
                f"domain_knowledge must be DomainKnowledge, "
                f"got {type(self.domain_knowledge).__name__}"
            )
        if not isinstance(self.decisions, list):
            raise TypeError(
                f"decisions must be list, got {type(self.decisions).__name__}"
            )
```

- [ ] **Step 4: Write tests for validation**

Add to `test_pipeline_state.py`:

```python
class TestPostInitValidation:
    """Verify __post_init__ catches invalid states."""

    def test_domain_knowledge_rejects_missing_vocab_keys(self):
        """Missing vocabulary keys raise ValueError."""
        from profiler.tools.pipeline_state import DomainKnowledge
        with pytest.raises(ValueError, match="vocabulary must contain keys"):
            DomainKnowledge(vocabulary={"operational": []})

    def test_domain_knowledge_rejects_missing_year_scope_keys(self):
        """Missing year_scope keys raise ValueError."""
        from profiler.tools.pipeline_state import DomainKnowledge
        with pytest.raises(ValueError, match="year_scope must contain keys"):
            DomainKnowledge(year_scope={"active": []})

    def test_discovery_state_rejects_wrong_source_tree_type(self):
        """source_tree as non-dict raises TypeError."""
        from profiler.tools.pipeline_state import DiscoveryState
        with pytest.raises(TypeError, match="source_tree must be dict or None"):
            DiscoveryState(source_tree="not_a_dict")  # type: ignore[arg-type]

    def test_pipeline_state_rejects_wrong_discovery_type(self):
        """discovery as non-DiscoveryState raises TypeError."""
        from profiler.tools.pipeline_state import PipelineState
        with pytest.raises(TypeError, match="discovery must be DiscoveryState"):
            PipelineState(discovery="bad")  # type: ignore[arg-type]
```

- [ ] **Step 5: Run validation tests**

Run: `python -m pytest profiler/tests/test_pipeline_state.py::TestPostInitValidation -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add profiler/tools/pipeline_state.py profiler/tests/test_pipeline_state.py
git commit -m "feat(pipeline-state): add post-init validation to dataclasses"
```

---

### Task 2: Version Migration Registry

**Files:**
- Modify: `profiler/tools/pipeline_state.py`
- Test: `profiler/tests/test_pipeline_state.py`

- [ ] **Step 1: Add version comparison helpers**

Add near top of `pipeline_state.py` (after the imports and `_ARTIFACT_FIELDS`):

```python
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
```

- [ ] **Step 2: Add migration registry + `_apply_migrations` classmethod**

Add after `_resolve_artifacts` near the bottom of `pipeline_state.py`:

```python
_CHECKPOINT_CURRENT_VERSION = "0.0.9"

# Registry: version_string -> list of migration functions.
# Each function takes and returns a raw dict (parsed YAML payload).
# Used to upgrade old checkpoint formats transparently on load.
_CHECKPOINT_MIGRATIONS: dict[str, list[Callable[[dict], dict]]] = {
    # Future entries: "0.0.8": [_migrate_v0_0_8_to_v0_0_9],
}


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
        if _version_less_than(version, from_ver) and _version_less_eq(from_ver, _CHECKPOINT_CURRENT_VERSION):
            for migrate_fn in _CHECKPOINT_MIGRATIONS[from_ver]:
                raw = migrate_fn(raw)

    raw["version"] = _CHECKPOINT_CURRENT_VERSION
    return raw
```

- [ ] **Step 3: Wire `_apply_migrations` into `load()`**

In `PipelineState.load()`, add the migration call after YAML parsing and before `_from_resolved_dict()`:

```python
@classmethod
def load(cls, path: str | Path) -> PipelineState:
    ...
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    ...
    if not isinstance(raw, dict):
        raise CommandError(...)

    # NEW: Apply migrations before resolving
    raw = cls._apply_migrations(raw)

    # Resolve _artifact references back into inline data
    base_dir = file_path.parent
    ...
```

- [ ] **Step 4: Write tests for version helpers + migration**

```python
class TestVersionMigration:
    """Verify version comparison and migration application."""

    def test_version_less_than(self):
        """_version_less_than compares correctly."""
        from profiler.tools.pipeline_state import _version_less_than
        assert _version_less_than("0.0.8", "0.0.9")
        assert _version_less_than("0.0.9", "0.1.0")
        assert not _version_less_than("0.0.9", "0.0.9")
        assert not _version_less_than("0.1.0", "0.0.9")

    def test_version_less_eq(self):
        """_version_less_eq compares correctly."""
        from profiler.tools.pipeline_state import _version_less_eq
        assert _version_less_eq("0.0.9", "0.0.9")
        assert _version_less_eq("0.0.8", "0.0.9")
        assert not _version_less_eq("0.1.0", "0.0.9")

    def test_apply_migrations_noop_when_current(self, tmp_path):
        """Current version checkpoint passes through unchanged."""
        state = PipelineState()
        path = tmp_path / "state.yaml"
        state.save_checkpoint(path)
        loaded = PipelineState.load(path)
        assert loaded.version == "0.0.9"

    def test_apply_migrations_bumps_version(self, tmp_path):
        """Old version checkpoint gets version bumped."""
        # Manually craft a v0.0.8 checkpoint
        raw = {
            "version": "0.0.8",
            "discovery": {"source_tree": {}, "workbook_index": []},
            "domain_knowledge": {"domain": "test", "vocabulary": {
                "operational": [], "reference": [], "support": [], "derived": [],
            }, "year_scope": {"active": [], "archived": [], "forward": []}},
        }
        path = tmp_path / "old-state.yaml"
        import yaml
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        loaded = PipelineState.load(path)
        assert loaded.version == "0.0.9"
        assert loaded.domain_knowledge.domain == "test"
```

- [ ] **Step 5: Run migration tests**

Run: `python -m pytest profiler/tests/test_pipeline_state.py::TestVersionMigration -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add profiler/tools/pipeline_state.py profiler/tests/test_pipeline_state.py
git commit -m "feat(pipeline-state): add version migration registry with apply_migrations"
```

---

### Task 3: DecisionRecord Dataclass and Decision Infrastructure

**Files:**
- Modify: `profiler/tools/pipeline_state.py`
- Test: `profiler/tests/test_pipeline_state.py`

- [ ] **Step 1: Add `DecisionRecord` dataclass**

Add after `DeepProfileIndex` and before `DomainKnowledge`:

```python
@dataclass
class DecisionRecord:
    """An autonomous or reviewed decision made during a pipeline phase.

    Each decision carries a confidence score, reasoning, and whether
    the consultant overrode it.  Accumulated across engagements, these
    records form the judgment taxonomy (see ``docs/agent-harness.md``).

    Attributes:
        phase: Pipeline phase name (``"discover"``, ``"score_and_select"``,
            ``"deep_profile"``, ``"derive_contracts"``).
        decision_type: Category of decision (``"tab_scoring"``,
            ``"fk_candidate"``, ``"model_name"``, etc.).
        entity_ref: What was decided about — a tab title, column name, or
            other identifier.
        value: The chosen value.
        confidence: Agent confidence from 0.0 (low) to 1.0 (high).
        reasoning: Natural language explanation of why the agent chose this.
        overridden: Whether a consultant overrode this decision.
        override_value: The consultant's chosen value, if overridden.
        overridden_at: ISO-8601 timestamp of the override, if overridden.
    """

    phase: str
    decision_type: str
    entity_ref: str
    value: Any
    confidence: float
    reasoning: str
    overridden: bool = False
    override_value: Any | None = None
    overridden_at: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )
```

- [ ] **Step 2: Add `decisions` field and `record_decision()` to PipelineState**

```python
@dataclass
class PipelineState:
    ...
    decisions: list[DecisionRecord] = field(default_factory=list)
    # Private, non-serialized fields
    _config: dict[str, Any] = field(default=None, repr=False, compare=False)
    _out_dir: Path | None = field(default=None, repr=False, compare=False)
    _date_stamp: str | None = field(default=None, repr=False, compare=False)

    ...

    def record_decision(
        self,
        phase: str,
        decision_type: str,
        entity_ref: str,
        value: Any,
        confidence: float,
        reasoning: str,
    ) -> DecisionRecord:
        """Record an autonomous pipeline decision.

        Args:
            phase: Pipeline phase name.
            decision_type: Category of decision.
            entity_ref: What was decided about.
            value: The chosen value.
            confidence: Agent confidence 0.0–1.0.
            reasoning: Why the agent chose this.

        Returns:
            The newly created DecisionRecord.
        """
        record = DecisionRecord(
            phase=phase,
            decision_type=decision_type,
            entity_ref=entity_ref,
            value=value,
            confidence=confidence,
            reasoning=reasoning,
        )
        self.decisions.append(record)
        return record
```

- [ ] **Step 3: Write DecisionRecord + decisions to checkpoint**

Update `_to_dict_with_artifacts` to include decisions:

```python
def _to_dict_with_artifacts(self, base_dir: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": self.version,
        "discovery": {},
        "domain_knowledge": asdict(self.domain_knowledge),
        "decisions": [asdict(d) for d in self.decisions],
    }
    ...
```

- [ ] **Step 4: Read decisions from checkpoint on load**

Update `_from_resolved_dict`:

```python
@classmethod
def _from_resolved_dict(cls, raw: dict[str, Any], base_dir: Path) -> PipelineState:
    ...
    decisions_raw = raw.get("decisions") or []
    decisions = []
    for d in decisions_raw:
        try:
            decisions.append(DecisionRecord(**d))
        except (TypeError, ValueError):
            logger.warning("skipping malformed decision record: %s", d)
    ...
    return cls(
        ...
        decisions=decisions,
    )
```

- [ ] **Step 5: Write tests for DecisionRecord**

```python
class TestDecisionRecord:
    """Verify DecisionRecord creation and validation."""

    def test_decision_record_defaults(self):
        """DecisionRecord fields are stored as provided."""
        from profiler.tools.pipeline_state import DecisionRecord
        dr = DecisionRecord(
            phase="discover",
            decision_type="tab_scoring",
            entity_ref="Crop Planner",
            value=0.85,
            confidence=0.75,
            reasoning="Matches operational tokens: crop",
        )
        assert dr.phase == "discover"
        assert dr.decision_type == "tab_scoring"
        assert dr.entity_ref == "Crop Planner"
        assert dr.value == 0.85
        assert dr.confidence == 0.75
        assert not dr.overridden

    def test_decision_record_confidence_bounds(self):
        """Confidence outside 0.0–1.0 raises ValueError."""
        from profiler.tools.pipeline_state import DecisionRecord
        with pytest.raises(ValueError, match="confidence must be between"):
            DecisionRecord(
                phase="test", decision_type="test", entity_ref="x",
                value=1, confidence=1.5, reasoning="bad",
            )
        with pytest.raises(ValueError, match="confidence must be between"):
            DecisionRecord(
                phase="test", decision_type="test", entity_ref="x",
                value=1, confidence=-0.1, reasoning="bad",
            )

    def test_decision_record_overridden(self):
        """Overridden fields are populated correctly."""
        from profiler.tools.pipeline_state import DecisionRecord
        dr = DecisionRecord(
            phase="score_and_select",
            decision_type="tab_scoring",
            entity_ref="Annual Budget",
            value=0.3,
            confidence=0.4,
            reasoning="Low score",
            overridden=True,
            override_value=0.8,
            overridden_at="2026-05-27T10:00:00",
        )
        assert dr.overridden
        assert dr.override_value == 0.8
```

- [ ] **Step 6: Write tests for decision round-trip through checkpoint**

```python
class TestDecisionsRoundTrip:
    """Verify decisions survive save_checkpoint → load."""

    def test_decisions_round_trip(self, tmp_path):
        """Decision records are preserved through checkpoint save/load."""
        from profiler.tools.pipeline_state import DecisionRecord, PipelineState
        state = PipelineState()
        state.record_decision(
            phase="discover",
            decision_type="tab_scoring",
            entity_ref="Crop Planner",
            value=0.85,
            confidence=0.75,
            reasoning="Matches operational tokens",
        )
        state.record_decision(
            phase="discover",
            decision_type="tab_scoring",
            entity_ref="Annual Budget",
            value=0.3,
            confidence=0.4,
            reasoning="Low match score",
        )
        path = tmp_path / "state.yaml"
        state.save_checkpoint(path)

        loaded = PipelineState.load(path)
        assert len(loaded.decisions) == 2
        assert loaded.decisions[0].entity_ref == "Crop Planner"
        assert loaded.decisions[0].confidence == 0.75
        assert loaded.decisions[1].entity_ref == "Annual Budget"
        assert loaded.decisions[1].confidence == 0.4

    def test_record_decision_returns_record(self):
        """record_decision appends and returns the record."""
        from profiler.tools.pipeline_state import PipelineState
        state = PipelineState()
        dr = state.record_decision(
            phase="test", decision_type="test", entity_ref="x",
            value=1, confidence=0.5, reasoning="test",
        )
        assert dr in state.decisions
        assert len(state.decisions) == 1
```

- [ ] **Step 7: Run decision tests**

Run: `python -m pytest profiler/tests/test_pipeline_state.py::TestDecisionRecord profiler/tests/test_pipeline_state.py::TestDecisionsRoundTrip -v`
Expected: 5 PASS

- [ ] **Step 8: Commit**

```bash
git add profiler/tools/pipeline_state.py profiler/tests/test_pipeline_state.py
git commit -m "feat(pipeline-state): add DecisionRecord dataclass with checkpoint round-trip"
```

---

### Task 4: Artifact Path Derivation + Contract Resolution

**Files:**
- Modify: `profiler/tools/pipeline_state.py`
- Test: `profiler/tests/test_pipeline_state.py`

- [ ] **Step 1: Fix `_to_dict_with_artifacts` to use checkpoint-relative contract paths**

Replace the hardcoded contract artifact paths:

```python
# Old hardcoded paths
if self.schema_contract:
    payload["schema_contract"] = {"_artifact": "build/schema-contract.yaml"}
if self.interaction_contract:
    payload["interaction_contract"] = {"_artifact": "build/interaction-contract.yaml"}
```

Replace with:

```python
if self.schema_contract:
    artifact_rel = str((base_dir / "schema-contract.yaml").relative_to(base_dir))
    payload["schema_contract"] = {"_artifact": artifact_rel}
if self.interaction_contract:
    artifact_rel = str((base_dir / "interaction-contract.yaml").relative_to(base_dir))
    payload["interaction_contract"] = {"_artifact": artifact_rel}
```

Since `base_dir` is already the parent directory of the checkpoint, `relative_to(base_dir)` simplifies to just the filename. So the code simplifies to:

```python
if self.schema_contract:
    payload["schema_contract"] = {"_artifact": "schema-contract.yaml"}
if self.interaction_contract:
    payload["interaction_contract"] = {"_artifact": "interaction-contract.yaml"}
```

- [ ] **Step 2: Pass `base_dir` to `_from_resolved_dict` and resolve contracts**

Change the `_from_resolved_dict` signature:

```python
@classmethod
def _from_resolved_dict(
    cls, raw: dict[str, Any], base_dir: Path | None = None
) -> PipelineState:
```

Update the call site in `load()`:

```python
return cls._from_resolved_dict(resolved, base_dir=base_dir)
```

Add contract resolution inside `_from_resolved_dict`:

```python
# Contract resolution — resolve artifact references to inline data
schema_contract = None
interaction_contract = None
if base_dir is not None:
    schema_raw = raw.get("schema_contract")
    if schema_raw:
        resolved_schema = _resolve_artifacts(schema_raw, base_dir)
        if isinstance(resolved_schema, dict) and resolved_schema:
            schema_contract = resolved_schema

    interaction_raw = raw.get("interaction_contract")
    if interaction_raw:
        resolved_interaction = _resolve_artifacts(interaction_raw, base_dir)
        if isinstance(resolved_interaction, dict) and resolved_interaction:
            interaction_contract = resolved_interaction
```

Update the return to use resolved contracts:

```python
return cls(
    ...
    schema_contract=schema_contract,
    interaction_contract=interaction_contract,
)
```

Remove the old hardcoded `None`:

```python
# REMOVE these lines:
schema_contract=None,  # Loaded from artifact on demand
interaction_contract=None,
```

- [ ] **Step 3: Write tests for contract resolution**

```python
class TestContractResolution:
    """Verify contract artifacts survive save_checkpoint → load."""

    def test_schema_contract_round_trip(self, tmp_path):
        """Schema contract is preserved through checkpoint save/load."""
        from profiler.tools.pipeline_state import PipelineState
        state = PipelineState(
            schema_contract={"tables": [{"name": "CropPlan"}]},
        )
        path = tmp_path / "state.yaml"
        state.save_checkpoint(path)

        loaded = PipelineState.load(path)
        assert loaded.schema_contract == {"tables": [{"name": "CropPlan"}]}

    def test_interaction_contract_round_trip(self, tmp_path):
        """Interaction contract is preserved through checkpoint save/load."""
        from profiler.tools.pipeline_state import PipelineState
        state = PipelineState(
            interaction_contract={"views": [{"name": "crop_list"}]},
        )
        path = tmp_path / "state.yaml"
        state.save_checkpoint(path)

        loaded = PipelineState.load(path)
        assert loaded.interaction_contract == {"views": [{"name": "crop_list"}]}

    def test_contracts_default_to_none(self):
        """Fresh state has None contracts."""
        from profiler.tools.pipeline_state import PipelineState
        state = PipelineState()
        assert state.schema_contract is None
        assert state.interaction_contract is None
```

- [ ] **Step 4: Write test for artifact path in saved YAML**

```python
class TestArtifactPaths:
    """Verify artifact paths are derived from checkpoint location."""

    def test_contract_artifact_paths_relative_to_checkpoint(self, tmp_path):
        """Contract artifact paths are checkpoint-relative, not hardcoded."""
        from profiler.tools.pipeline_state import PipelineState
        state = PipelineState(
            schema_contract={"tables": []},
            interaction_contract={"views": []},
        )
        path = tmp_path / "checkpoints" / "pipeline-state.yaml"
        path.parent.mkdir(parents=True)
        state.save_checkpoint(path)

        yaml_text = path.read_text()
        assert "schema-contract.yaml" in yaml_text
        assert "interaction-contract.yaml" in yaml_text
        assert "build/" not in yaml_text  # No hardcoded build/ path
```

- [ ] **Step 5: Run contract + artifact tests**

Run: `python -m pytest profiler/tests/test_pipeline_state.py::TestContractResolution profiler/tests/test_pipeline_state.py::TestArtifactPaths -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add profiler/tools/pipeline_state.py profiler/tests/test_pipeline_state.py
git commit -m "feat(pipeline-state): resolve contracts on load, use checkpoint-relative artifact paths"
```

---

### Task 5: Config Routing and Helper Methods

**Files:**
- Modify: `profiler/tools/pipeline_state.py`
- Test: `profiler/tests/test_pipeline_state.py`

- [ ] **Step 1: Add `configure()` method to PipelineState**

```python
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
        Self for chaining.
    """
    from datetime import date
    self._config = config or self._config or {}
    self._out_dir = Path(out_dir) if out_dir else (self._out_dir or Path("data/profile_snapshots"))
    self._date_stamp = date_stamp or self._date_stamp or date.today().isoformat()
    return self
```

- [ ] **Step 2: Add helper methods moved from management command**

```python
@staticmethod
def _load_json_artifact(path: str | Path | None, default: Any) -> Any:
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
def _build_google_services():
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
```

- [ ] **Step 3: Wire config through `load_or_create`**

Update `load_or_create` to accept `out_dir` and `date_stamp`:

```python
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
```

Inside, after constructing the state, call `configure()`:

```python
# At the end of load_or_create, before return:
state.configure(config=config, out_dir=out_dir, date_stamp=date_stamp)
return state
```

Make sure `config_path` is read in all branches. Currently it's only read in the "fresh" branch — the existing checkpoint branch skips config reading:

```python
if checkpoint_path.exists():
    state = cls.load(checkpoint_path)
    # Need to configure even loaded state
    state._read_and_store_config(config_path)
    ...
```

Actually, let me simplify. Read the config at the top of `load_or_create`, then always configure:

```python
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
    if checkpoint_path is None:
        checkpoint_path = Path(str(config_path)).with_suffix(".yaml")
    checkpoint_path = Path(checkpoint_path)

    # Read config JSON
    config_file = Path(config_path)
    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
            config = {k: v for k, v in config.items() if not k.startswith("_")}
        except (json.JSONDecodeError, OSError):
            config = {}

    if checkpoint_path.exists():
        state = cls.load(checkpoint_path)
    elif domain_context is not None:
        state = cls(
            domain_knowledge=DomainKnowledge.from_domain_context(domain_context)
        )
    else:
        state = cls()
        domain_val = config.get("domain")
        if domain_val:
            state.domain_knowledge.domain = str(domain_val)

    state.configure(config=config, out_dir=out_dir, date_stamp=date_stamp)
    return state
```

- [ ] **Step 4: Write tests**

```python
class TestConfigRouting:
    """Verify config is properly routed to phase methods."""

    def test_configure_sets_fields(self):
        """configure() stores config, out_dir, date_stamp."""
        from profiler.tools.pipeline_state import PipelineState
        state = PipelineState()
        state.configure(
            config={"domain": "test"},
            out_dir="/tmp/test_out",
            date_stamp="2026-05-27",
        )
        assert state._config == {"domain": "test"}
        assert str(state._out_dir) == "/tmp/test_out"
        assert state._date_stamp == "2026-05-27"

    def test_load_or_create_stores_config(self, tmp_path):
        """load_or_create stores config on fresh PipelineState."""
        config_path = tmp_path / "config.json"
        config_path.write_text('{"domain": "farm_test"}')

        from profiler.tools.pipeline_state import PipelineState
        state = PipelineState.load_or_create(config_path=config_path)
        assert state._config.get("domain") == "farm_test"
```

- [ ] **Step 5: Run config tests**

Run: `python -m pytest profiler/tests/test_pipeline_state.py::TestConfigRouting -v`
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add profiler/tools/pipeline_state.py profiler/tests/test_pipeline_state.py
git commit -m "feat(pipeline-state): add config routing and helper methods"
```

---

### Task 6: Phase Method Rewrites

**Files:**
- Modify: `profiler/tools/pipeline_state.py`
- Test: `profiler/tests/test_pipeline_state.py`

- [ ] **Step 1: Rewrite `discover()` with delegation + decision recording**

```python
def discover(
    self,
    drive_service=None,
    sheets_service=None,
) -> PipelineState:
    """Phase 0/1: Discover source tree, enumerate workbooks, score and select tabs.

    Delegates to ``run_cohort_corpus()`` for the actual profiling work,
    then maps results onto PipelineState fields and records scoring decisions.

    Args:
        drive_service: Google Drive service handle.
        sheets_service: Google Sheets service handle.

    Returns:
        Self for chaining.

    Raises:
        RuntimeError: If ``source_tree`` is already populated.
    """
    if self.discovery.source_tree is not None:
        raise RuntimeError("discover: source_tree already populated")

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

    # Record scoring decisions from shortlist
    for tab in (self.discovery.shortlist or []):
        score = tab.get("score", 0)
        confidence = min(abs(score) / 100.0, 1.0) if score else 0.5
        self.record_decision(
            phase="discover",
            decision_type="tab_scoring",
            entity_ref=tab.get("tab_title", "unknown"),
            value=score,
            confidence=confidence,
            reasoning=tab.get("scoring_rationale", "Score from heuristics"),
        )

    return self
```

Add the `import datetime` / `from datetime import date` at the top of the file if not already there.

- [ ] **Step 2: Rewrite `score_and_select()` with re-scoring**

```python
def score_and_select(self) -> PipelineState:
    """Phase 1/2: Re-score and select tabs from stored data (no API calls).

    Uses stored ``broad_inventory`` and ``domain_knowledge.vocabulary``
    to re-score all tabs and update ``shortlist`` / ``approved_tabs``.

    Returns:
        Self for chaining.

    Raises:
        RuntimeError: If ``discover()`` has not been run or ``shortlist`` is ``None``.
    """
    if self.discovery.source_tree is None:
        raise RuntimeError("score_and_select: discover() must run first")
    if self.discovery.shortlist is None:
        raise RuntimeError("score_and_select: shortlist is None")

    from profiler.tools.cohort_corpus import score_tab
    from profiler.tools.domain_context import (
        DomainContext,
        merge_vocabulary,
    )

    # Build a DomainContext from our stored DomainKnowledge for compatibility
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
            strategy=self.domain_knowledge.deduplication.get("strategy", "latest_year"),
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

        # Normalize score to 0.0–1.0 range for confidence
        max_possible = 100
        normalized = min(raw_score / max_possible, 1.0) if max_possible else 0.0

        entry = {
            "tab_title": title,
            "score": raw_score,
            "confidence": normalized,
            "scoring_rationale": "; ".join(reasons) if reasons else "No domain match",
            "breakdown": breakdown,
        }
        scored_tabs.append(entry)

        self.record_decision(
            phase="score_and_select",
            decision_type="tab_scoring",
            entity_ref=title,
            value=raw_score,
            confidence=normalized,
            reasoning=entry["scoring_rationale"],
        )

    self.discovery.shortlist = scored_tabs

    # Auto-select high-confidence tabs (confidence >= 0.90)
    approved: dict[str, list[str]] = {}
    for tab in scored_tabs:
        if tab["confidence"] >= 0.90:
            # Group by workbook — requires workbook_code from broad_inventory
            # Since we don't have it in scored_tabs, use a simple flat list
            approved.setdefault("auto_selected", []).append(tab["tab_title"])
    self.discovery.approved_tabs = approved

    return self
```

- [ ] **Step 3: Rewrite `deep_profile()` with delegation**

```python
def deep_profile(self, sheets_service=None) -> PipelineState:
    """Phase 3: Deep-profile approved tabs.

    Delegates to ``run_cohort_corpus()`` in resume mode with the
    current ``approved_tabs``, then populates ``deep_profile_index.entries``.

    Args:
        sheets_service: Google Sheets service handle.

    Returns:
        Self for chaining.

    Raises:
        RuntimeError: If ``approved_tabs`` is ``None``.
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
        self.deep_profile_index.entries = list(deep_coverage.values())

    # Record FK candidate decisions
    for entry in self.deep_profile_index.entries:
        for fk_candidate in entry.get("fk_candidates") or []:
            confidence = fk_candidate.get("confidence", 0.5)
            self.record_decision(
                phase="deep_profile",
                decision_type="fk_candidate",
                entity_ref=f"{entry.get('tab', 'unknown')}.{fk_candidate.get('column', 'unknown')}",
                value=fk_candidate.get("target"),
                confidence=confidence,
                reasoning=fk_candidate.get("rationale", "FK candidate from column analysis"),
            )

    return self
```

- [ ] **Step 4: Rewrite `derive_contracts()`**

```python
def derive_contracts(self) -> PipelineState:
    """Derive schema and interaction contracts from profile data.

    Currently creates placeholder contracts from deep profile data.
    Future versions will delegate to ``scaffold_workbook_schema``.

    Returns:
        Self for chaining.

    Raises:
        RuntimeError: If ``deep_profile_index.entries`` is empty.
    """
    if not self.deep_profile_index.entries:
        raise RuntimeError("derive_contracts: deep_profile must run first")

    # Build a basic schema contract from deep profile entries
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

        model_name = "".join(
            word.capitalize() for word in tab_name.replace("-", "_").replace(" ", "_").split("_")
        )
        table = {
            "model_name": model_name,
            "source_tab": tab_name,
            "fields": fields,
        }
        tables.append(table)

        self.record_decision(
            phase="derive_contracts",
            decision_type="model_name",
            entity_ref=tab_name,
            value=model_name,
            confidence=0.7,
            reasoning=f"Derived model name '{model_name}' from tab title '{tab_name}'",
        )

    self.schema_contract = {"tables": tables}
    self.interaction_contract = {"views": []}

    return self
```

- [ ] **Step 5: Write tests for phase methods**

```python
class TestPhaseMethods:
    """Verify phase methods delegate, populate fields, and record decisions."""

    @patch("profiler.tools.cohort_corpus.run_cohort_corpus")
    def test_discover_delegates_and_records_decisions(self, mock_run, tmp_path):
        """discover() calls run_cohort_corpus and records decisions."""
        from profiler.tools.pipeline_state import PipelineState
        mock_run.return_value = {
            "discovery": "",
            "index": "",
            "broad_coverage": "",
            "tab_shortlist": "",
            "tab_selection": "",
        }

        state = PipelineState()
        state.configure(out_dir=str(tmp_path), date_stamp="2026-05-27")
        state.discover()

        assert mock_run.called
        assert state.discovery.source_tree == {}
        assert state.discovery.workbook_index == []

    @patch("profiler.tools.cohort_corpus.score_tab")
    def test_score_and_select_records_decisions(self, mock_score):
        """score_and_select() records scoring decisions."""
        from profiler.tools.pipeline_state import (
            PipelineState, DiscoveryState, DomainKnowledge,
        )
        mock_score.return_value = (50, ["operational_tab_name"], {})

        state = PipelineState(
            discovery=DiscoveryState(
                source_tree={},
                workbook_index=[],
                broad_inventory=[{"tab_title": "Crop Planner", "row_count": 100, "column_count": 20}],
                shortlist=[],  # not None, so guard passes
            ),
            domain_knowledge=DomainKnowledge(
                domain="farm",
                vocabulary={
                    "operational": ["crop", "field"],
                    "reference": [],
                    "support": [],
                    "derived": [],
                },
            ),
        )
        state.configure(date_stamp="2026-05-27")
        result = state.score_and_select()
        assert len(result.decisions) == 1
        assert result.decisions[0].decision_type == "tab_scoring"
        assert result.decisions[0].entity_ref == "Crop Planner"

    def test_derive_contracts_creates_tables(self):
        """derive_contracts() builds tables from deep profile entries."""
        from profiler.tools.pipeline_state import PipelineState, DeepProfileIndex
        state = PipelineState(
            deep_profile_index=DeepProfileIndex(entries=[
                {"tab": "Crop Planner", "columns": [
                    {"header": "crop_name", "data_type": "string"},
                    {"header": "planting_date", "data_type": "date"},
                ]},
            ]),
        )
        result = state.derive_contracts()
        assert result.schema_contract is not None
        assert len(result.schema_contract["tables"]) == 1
        assert result.schema_contract["tables"][0]["model_name"] == "CropPlanner"
        assert len(result.schema_contract["tables"][0]["fields"]) == 2
        assert len(result.decisions) == 1
        assert result.decisions[0].decision_type == "model_name"
```

- [ ] **Step 6: Run phase method tests**

Run: `python -m pytest profiler/tests/test_pipeline_state.py::TestPhaseMethods -v`
Expected: 3 PASS

- [ ] **Step 7: Run complete test suite for pipeline_state**

Run: `python -m pytest profiler/tests/test_pipeline_state.py -v`
Expected: All existing + new tests PASS

- [ ] **Step 8: Commit**

```bash
git add profiler/tools/pipeline_state.py profiler/tests/test_pipeline_state.py
git commit -m "feat(pipeline-state): rewrite phase methods with delegation and decision recording"
```

---

### Task 7: Management Command Refactoring

**Files:**
- Modify: `profiler/management/commands/run_pipeline_state.py`
- Modify: `profiler/tests/test_run_pipeline_state_command.py`

- [ ] **Step 1: Simplify `handle()` to thin wrapper**

Replace the phase-dispatch logic with a unified approach that calls `state.phase()`:

```python
def handle(self, *args, **options):
    config_path = Path(options["config"]).resolve()
    if not config_path.is_file():
        raise CommandError(f"Config file not found: {config_path}")

    checkpoint_path = Path(options["checkpoint"]).resolve()
    phase = options["phase"]
    out_dir = Path(options["out_dir"]).resolve()
    date_stamp = options.get("date_stamp") or date.today().isoformat()
    stop_before_deep = options.get("stop_before_deep", False)

    # Load or create PipelineState with config routing
    state = PipelineState.load_or_create(
        config_path=config_path,
        checkpoint_path=checkpoint_path,
        out_dir=out_dir,
        date_stamp=date_stamp,
    )

    if phase == "all":
        self._run_all(state, checkpoint_path)
    elif phase == "discover":
        self._run_phase(state, "discover", checkpoint_path)
    elif phase == "score_and_select":
        self._run_phase(state, "score_and_select", checkpoint_path)
    elif phase == "deep_profile":
        self._run_phase(state, "deep_profile", checkpoint_path)
    elif phase == "derive_contracts":
        self._run_phase(state, "derive_contracts", checkpoint_path)
    else:
        self._run_phase(state, phase, checkpoint_path)
```

- [ ] **Step 2: Add `_run_phase` helper**

```python
def _run_phase(
    self, state: PipelineState, phase: str, checkpoint_path: Path
) -> None:
    """Execute a single phase and save checkpoint.

    Builds Google services if the phase needs them, calls
    ``state.<phase>()`` with appropriate kwargs, and saves the
    checkpoint.

    Args:
        state: Pipeline state.
        phase: Phase method name.
        checkpoint_path: Checkpoint file path.
    """
    # Build kwargs for the phase method
    kwargs: dict[str, Any] = {}
    if phase in ("discover", "deep_profile"):
        drive_service, sheets_service = self._build_services()
        if phase == "discover":
            kwargs["drive_service"] = drive_service
        kwargs["sheets_service"] = sheets_service

    # Call the phase method
    getattr(state, phase)(**kwargs)
    state.save_checkpoint(checkpoint_path)
    self.stdout.write(
        self.style.SUCCESS(f"{phase} → {checkpoint_path}")
    )
```

- [ ] **Step 3: Simplify `_run_all`**

```python
def _run_all(self, state: PipelineState, checkpoint_path: Path) -> None:
    """Run all phases sequentially, skipping completed ones."""
    if state.discovery.source_tree is None:
        self._run_phase(state, "discover", checkpoint_path)
    else:
        self.stdout.write("[skip] discover already complete")

    if state.discovery.shortlist is None:
        self._run_phase(state, "score_and_select", checkpoint_path)
    else:
        self.stdout.write("[skip] score_and_select already complete")

    if not state.deep_profile_index.entries:
        self._run_phase(state, "deep_profile", checkpoint_path)
    else:
        self.stdout.write("[skip] deep_profile already complete")

    if state.schema_contract is None:
        self._run_phase(state, "derive_contracts", checkpoint_path)
    else:
        self.stdout.write("[skip] derive_contracts already complete")
```

- [ ] **Step 4: Remove obsolete methods**

Remove entirely:
- `_run_discover()` — all logic moved into PipelineState.discover()
- `_run_score_and_select()` — all logic moved into PipelineState.score_and_select()
- `_run_deep_profile()` — all logic moved into PipelineState.deep_profile()
- `_run_derive_contracts()` — all logic moved into PipelineState.derive_contracts()
- `_today_stamp()` — moved to PipelineState
- `_load_json_artifact()` — moved to PipelineState

Keep only:
- `handle()`
- `_run_phase()` (new)
- `_run_all()` (simplified)
- `_build_services()` (keep, used by _run_phase)

- [ ] **Step 5: Update command tests**

Update `test_run_pipeline_state_command.py` — the existing tests should mostly still work because they mock `run_cohort_corpus` and test at the command level. The main changes:

- Remove the `_stub` entry test (that was a hack in the old `_run_derive_contracts`)
- Tests that check `"Phase 0/1 complete"` output may need updating since output messages changed

Update the message assertions:

```python
# In test_run_pipeline_state_discover_phase:
# Change:
assert "Phase 0/1 complete" in out.getvalue()
# To:
assert "discover" in out.getvalue()

# In test_run_pipeline_state_all_phase:
# Change:
assert "Phase 0/1 complete" in output
# To:
assert "discover" in output
```

And update the `test_run_pipeline_state_resume` test — the skip message check is the same but the derive_contracts flow no longer seeds a stub:

```python
# In test_run_pipeline_state_resume:
# The old test expected derive_contracts to complete.
# Now state.schema_contract starts as None, so it should still run.
# The assertion should remain the same.
```

- [ ] **Step 6: Run command tests**

Run: `python -m pytest profiler/tests/test_run_pipeline_state_command.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add profiler/management/commands/run_pipeline_state.py profiler/tests/test_run_pipeline_state_command.py
git commit -m "refactor(run-pipeline-state): thin CLI wrapper delegating to PipelineState methods"
```

---

### Task 8: Integration Verification

**Files:**
- `profiler/tests/test_pipeline_state.py`
- `profiler/tests/test_run_pipeline_state_command.py`

- [ ] **Step 1: Run full test suite for both test files**

Run: `python -m pytest profiler/tests/test_pipeline_state.py profiler/tests/test_run_pipeline_state_command.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run LSP diagnostics on changed files**

Check: `python -m py_compile profiler/tools/pipeline_state.py`
and: `python -m py_compile profiler/management/commands/run_pipeline_state.py`

- [ ] **Step 3: Run full chassis gate if available**

Run: `make chassis-gate` (from repo root) — or at minimum the relevant test suite.

- [ ] **Step 4: Commit any final fixes**
