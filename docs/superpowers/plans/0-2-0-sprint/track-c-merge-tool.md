# Track C: Merge Tool

> **Goal:** Build the tool that merges profiler signals + human interaction contract → codegen manifest. Update `merge_discovery_notes` to write to the interaction contract layer.  
> **Duration:** Week 2  
> **Risk:** Medium  
> **Worktree:** `.worktrees/track-c-merge-tool/`  
> **Branch:** `0-2-0/track-c-merge-tool`

---

## Worktree Setup

```bash
# From repo root
git branch 0-2-0/track-c-merge-tool master
git worktree add .worktrees/track-c-merge-tool 0-2-0/track-c-merge-tool
cd .worktrees/track-c-merge-tool
```

**Agent rules:** Only touch files listed in this track. Do not edit files in other tracks' scopes. Commit to `0-2-0/track-c-merge-tool` branch only.

**Cross-track note:** This track depends on Track B's signals format. Read `track-b-profiler-signals.md` for the expected YAML schema, but do not block on Track B's implementation.

---

## Context

The interaction contract design (`docs/interaction-contract.md`) separates machine-generated signals from human decisions. This track implements the merge layer: combining profiler signals (Layer 1) with the human interaction contract (Layer 2) into a codegen manifest (Layer 3) that `generate_admin` consumes.

The existing `merge_discovery_notes` command patches a flat `view-manifest.yaml`. This track redirects it to produce the human interaction contract layer, and adds a new merge command for the final codegen manifest.

---

## Files

**New:**
- `workbook/management/commands/merge_interaction_contract.py` — Merge signals + human contract → codegen manifest
- `workbook/tests/test_merge_interaction_contract.py` — Merge semantics tests

**Modified:**
- `workbook/management/commands/merge_discovery_notes.py` — Output to `interaction-contract.yaml`
- `workbook/management/commands/generate_admin.py` — Accept `--codegen-manifest`
- `workbook/tests/test_discovery.py` — Update for new output format

---

## Design Decisions

1. **Human overrides are persistent.** Re-running the profiler and merge preserves human-confirmed archetypes, role owners, and workflow notes.
2. **Removed tabs are marked deprecated, not deleted.** The human interaction contract retains the entry so historical decisions are auditable.
3. **Dependency graph edges are machine-managed.** The human does not edit edges; they reflect actual spreadsheet formula references. If edges change, the codegen manifest updates automatically.
4. **Backward-compatible:** `generate_admin --manifest` still accepts old flat view-manifest format.

---

## Merge Semantics

### Scenario: New Tab Appears in Signals

**Action:** Add to codegen manifest with empty human contract defaults.

```yaml
# codegen-manifest.yaml (new entry)
views:
  - name: new_tab
    entity: null
    source_tab: New Tab
    type: list  # default from signals archetype
    archetype_confidence: 0.65  # from signals
    role_owner: null  # human hasn't decided
    role_reviewers: []
    workflow_notes: null
```

### Scenario: Tab Removed from Signals

**Action:** Preserve human contract entry, mark `deprecated: true`.

```yaml
# codegen-manifest.yaml (deprecated entry)
views:
  - name: old_tab
    entity: old_entity
    deprecated: true
    # ... other fields preserved
```

### Scenario: Archetype Signal Changes

**Action:** Update `archetype_confidence` in codegen manifest. Do NOT override human-confirmed `archetype`.

```yaml
# If human previously set archetype: form, signal now says list
views:
  - name: crop_plan_entry
    type: form  # human value preserved
    archetype_confidence: 0.45  # updated from new signal (low, triggers alert)
```

### Scenario: Human Overrides Archetype

**Action:** Human value wins permanently. Signal confidence becomes informational only.

### Scenario: New Edge in Dependency Graph

**Action:** Add to codegen manifest automatically. No human action required.

### Scenario: Edge Removed from Graph

**Action:** Remove from codegen manifest. Log warning for operator review.

---

## Acceptance Criteria

- [ ] `merge_discovery_notes --signals profiler-signals.yaml --interview interview.md --out interaction-contract.yaml` produces human contract layer
- [ ] `merge_interaction_contract --signals profiler-signals.yaml --interaction-contract interaction-contract.yaml --out codegen-manifest.yaml` produces merged codegen manifest
- [ ] Re-running profiler and merge preserves human overrides (archetype, role_owner, workflow_notes)
- [ ] Removed tabs are marked `deprecated: true`, not deleted
- [ ] `generate_admin --codegen-manifest codegen-manifest.yaml` produces same output as `--manifest view-manifest.yaml`
- [ ] Test: merge preserves human archetype override across signal changes
- [ ] Test: merge handles new tab (adds with defaults)
- [ ] Test: merge handles removed tab (marks deprecated)
- [ ] Test: merge handles changed dependency graph (adds/removes edges)

---

## Tasks (Atomic)

### Task C1: Redirect merge_discovery_notes output
**Where:** `workbook/management/commands/merge_discovery_notes.py`  
**What:** Add `--signals` input argument. Write output to `interaction-contract.yaml` format instead of patching flat view manifest.

**Input:**
- `--signals profiler-signals.yaml` (from Track B)
- `--interview discovery-interview.md` (existing)

**Output:**
```yaml
version: interaction-contract-1
views:
  CropPlanner:
    archetype: form  # from interview or signals if not overridden
    role_owner: field_manager  # from interview
    role_reviewers: []
    workflow_notes: "Filled out every Monday"
    status_semantics:
      field: status
      values:
        - Planted: "Seed in ground"
```

**Verify:** Test that interview answers populate human contract fields.

### Task C2: Implement merge_interaction_contract command
**Where:** `workbook/management/commands/merge_interaction_contract.py`  
**What:** New management command implementing merge semantics table.

**Arguments:**
- `--signals` (required) — profiler-signals.yaml
- `--interaction-contract` (required) — interaction-contract.yaml
- `--out` (required) — codegen-manifest.yaml

**Algorithm:**
1. Load signals and human contract
2. For each view in signals:
   - If view exists in human contract: merge (human wins on conflicts)
   - If view is new: add with defaults
3. For each view in human contract not in signals: mark deprecated
4. Merge dependency graph from signals (human contract has no graph edits)
5. Write codegen manifest

**Verify:** All merge semantics scenarios have passing tests.

### Task C3: Update generate_admin for codegen manifest
**Where:** `workbook/management/commands/generate_admin.py`  
**What:** Add `--codegen-manifest` argument. Parse new format and produce identical admin.py output.

**Behavior:**
- `--codegen-manifest` → read new format
- `--manifest` → read old format (backward-compatible)
- Both arguments absent → error (must specify one)

**Verify:** Run same contract through both paths, compare generated admin.py (should be identical).

### Task C4: Merge semantics tests
**Where:** `workbook/tests/test_merge_interaction_contract.py`  
**What:** Comprehensive tests for each merge scenario.

```python
def test_merge_preserves_human_archetype():
    signals = {"views": {"CropPlanner": {"signals": {"ui_archetype": "list", "confidence": 0.45}}}}
    human = {"views": {"CropPlanner": {"archetype": "form"}}}
    result = merge(signals, human)
    assert result["views"]["CropPlanner"]["type"] == "form"
    assert result["views"]["CropPlanner"]["archetype_confidence"] == 0.45

def test_merge_adds_new_tab():
    signals = {"views": {"NewTab": {"signals": {"ui_archetype": "list"}}}}
    human = {"views": {}}
    result = merge(signals, human)
    assert "NewTab" in result["views"]
    assert result["views"]["NewTab"]["role_owner"] is None

def test_merge_marks_removed_tab_deprecated():
    signals = {"views": {}}
    human = {"views": {"OldTab": {"archetype": "form"}}}
    result = merge(signals, human)
    assert result["views"]["OldTab"]["deprecated"] is True
```

**Verify:** All tests pass.

### Task C5: Integration test
**Where:** `workbook/tests/`  
**What:** End-to-end round-trip.

```bash
# 1. Generate profiler signals
python manage.py scaffold_view_manifest --structure structure.json --signals-only --out signals.yaml

# 2. Generate and fill discovery interview
python manage.py generate_discovery_interview --signals signals.yaml --out interview.md
# (human fills in interview)

# 3. Merge into human contract
python manage.py merge_discovery_notes --signals signals.yaml --interview interview.md --out interaction-contract.yaml

# 4. Merge into codegen manifest
python manage.py merge_interaction_contract --signals signals.yaml --interaction-contract interaction-contract.yaml --out codegen-manifest.yaml

# 5. Generate admin
python manage.py generate_admin --contract contract.yaml --codegen-manifest codegen-manifest.yaml --out admin.py
```

**Verify:** Generated admin.py matches expected output.

---

## Non-Goals (Out of Scope)

- GUI for editing interaction contract
- Automated discovery interview generation (questionnaire is still manual)
- Role-to-permission mapping (product repo defines this)
- Real-time merge during profiling
