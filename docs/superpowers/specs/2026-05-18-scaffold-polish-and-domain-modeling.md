# Scaffold Polish and Domain-Modeling Workflow

> **Date:** 2026-05-18
> **Status:** Draft
> **Philosophy:** Human-in-the-loop — automation provides smart defaults, the human always reviews.

## Goal

Fix four scaffold bugs and extend the scaffold/profiler pipeline with a domain-modeling workflow that produces structurally sound contract drafts from profiler output + human-authored domain knowledge.

---

## Section A: Bug Fixes

### `_to_pascal_case` mangles PascalCase input

**File:** `workbook/management/commands/scaffold_workbook_schema.py:41`

`_to_pascal_case("SalesChannel")` → `"Saleschannel"` because `.capitalize()` lowercases all characters after the first. The fix is a simple pass-through check: if the input has no underscores/hyphens and contains uppercase after position 0, return it unchanged.

This also causes FK validation false positives: the validator compares `"SalesChannel"` (from the contract) against `"Saleschannel"` (the resolved class name), reporting the FK target as missing.

### Custom models overwritten on regenerate

**File:** `scripts/new_product.py:338` (`render_models_py`)

The scaffolded `models.py` contains `FarmUser(AbstractUser)` but no sentinel marker or `from .models_auto import *`. On first `generate_models`, `ensure_stub()` patches these in, but the output is ugly (import order, marker placement). Fix: include `MARKER` and the import in the template itself so the file is correct from day one.

### Root URL returns 404

**File:** `scripts/new_product.py:296` (`render_urls_py`)

Add `from django.views.generic import RedirectView` and `path("", RedirectView.as_view(url="/admin/", permanent=False))` as the first urlpattern so `/` redirects to the admin interface.

### No superuser creation path

**Files:** `scripts/new_product.py` (`render_makefile`, `render_env_example`)

Add a `createsuperuser` make target that supports `DJANGO_SUPERUSER_USERNAME` / `DJANGO_SUPERUSER_PASSWORD` env vars for non-interactive use, with fallback to interactive `createsuperuser`. Add these vars to the scaffolded `.env.example`.

---

## Section B: Domain-Modeling Workflow

### Problem

The scaffold produces one model per source tab with every column as a stored Django field. Entity boundaries, FK relationships, import keys, and computed fields are entirely absent. The human can fix this by writing a hand-crafted contract from scratch, but there is no intermediate representation to capture their domain expertise.

### Workflow

```
Source tabs ──→ Profiler ──→ profile JSON ──┐
                                              ├──→ scaffold_workbook_schema ──→ Contract YAML
Domain knowledge YAML ───────────────────────┘         ↑
                                            Heuristics layer:
                                            - FK column detection
                                            - computed_fields from formula_pattern
                                            - tab grouping candidates
```

1. **Profiler** scans source tabs → raw column/type/formula data (unchanged)
2. **Human** writes `docs/domain-knowledge.yaml` — entities, fields, types, FK targets, import keys
3. **Heuristics** (always-on) enrich the scaffold output: FK-like columns get flagged, formula columns become `computed_fields`, shared-header tabs get merge candidates
4. **scaffold_workbook_schema --domain-knowledge** merges domain knowledge with profiler data: matching fields adopt declared types; unmatched profiler columns become review notes
5. **Human reviews** the output contract and the schema-contract.md checklist, iterates until satisfactory

### Component 1: Domain Knowledge YAML Schema

File: `docs/domain-knowledge.example.yaml` (scaffolded alongside `.env.example`)

```yaml
# docs/domain-knowledge.yaml — Entity definitions for contract generation
# Used by: scaffold_workbook_schema --domain-knowledge docs/domain-knowledge.yaml

entities:
  Season:
    description: "Named set of planned plantings — the top-level organizational unit."
    source_tabs: ["Crop Planner"]
    fields:
      name:
        type: CharField
        max_length: 100
        unique: true
      year:
        type: PositiveIntegerField
      is_active:
        type: BooleanField
        default: false
    import_key: [name]
    fk_to: []

  Planting:
    description: "Individual planting record tied to a season and crop."
    source_tabs: ["Crop Planner", "Crop Plan 501+503+801"]
    fields:
      planting_id:
        type: CharField
        max_length: 50
        unique: true
      crop_variety:
        type: CharField
        max_length: 200
      season:
        type: ForeignKey
        to: Season
    import_key: [planting_id]
    fk_to: [Season]
```

Merge rules:
- If a domain-knowledge field name matches a profiler column's `suggested_field_name`, the domain type and kwargs override the profiler-inferred type
- Profiler columns not mentioned in the domain entity become `columns[]` entries with a `review_note: "Not mapped in domain knowledge"`
- Domain entities not matched to any profiler tab produce a warning
- `source_tabs` fields map domain entities to profiler tab names; unmatched tabs become standalone models as before

### Component 2: Heuristics (always-on, no flag)

**FK detection:** Columns ending in `_id`, or with names matching known entity names (`channel`, `season`, `crop`, `block`), get flagged with `suggested_fk_target` in the contract and a `review_note`.

**Computed fields:** Columns where profiler `formula_pattern` is `row_formula` or `expansion_formula` are removed from `columns[]` and added to `computed_fields{}` with a stub expression.

**Tab grouping:** Tabs from the same workbook series sharing 2+ column headers are annotated with `merge_candidates` in the contract for human review.

### Component 3: Schema Contract Template

File: `scripts/new_product.py` → `render_schema_contract_md()`

Replace the current 12-line blank template with a structured guide:

```
# Schema contract — {project_name}

## Entity Map YAML

This document is paired with `docs/domain-knowledge.yaml`.
Run the scaffold to merge domain knowledge with profiler data:

    scaffold_workbook_schema --bundle-config ... --domain-knowledge docs/domain-knowledge.yaml

## Entities

For each entity, document:
- **Purpose** — what real-world concept this represents
- **Source tabs** — which profiler tabs map to this entity
- **Fields** — name, type, constraints, and whether stored or computed
- **FK targets** — which other entities this references
- **Import key** — natural key for idempotent re-import

### Example: Season

```yaml
Season:
  purpose: "Named set of planned plantings"
  source_tabs: ["Crop Planner"]
  fields:
    name: CharField(unique=True)
    year: PositiveIntegerField
  import_key: [name]
```

## Decisions

Record rationale for each entity: Lift / modify / rebuild.

## Drift

Re-profile after source changes; note date and what changed.
```

### Component 4: Domain Knowledge Example

File: In `scripts/new_product.py`, add `render_domain_knowledge_example_yaml()` — creates `docs/domain-knowledge.example.yaml` with 2-3 fictional entities showing standalone models, FK parent-child, and computed fields.

---

## Files Changed

| File | Change |
|------|--------|
| `workbook/management/commands/scaffold_workbook_schema.py` | Fix `_to_pascal_case`; add `--domain-knowledge` flag; add heuristics (FK detection, computed_fields, tab grouping) |
| `scripts/new_product.py` | Update `render_models_py`; update `render_urls_py`; update `makefile` template; update `render_schema_contract_md`; add `render_domain_knowledge_example_yaml`; add `DJANGO_SUPERUSER_*` to env example |
| `workbook/makefile_targets.py` | Add `createsuperuser` target block |
| `workbook/codegen/contract.py` | Add `review_note` support to column schema (no behavioral change) |

---

## Non-Goals

- **Profiler rewrite** — entity grouping is scoped to heuristics in the scaffold, not re-engineering the profiler
- **Full formula parsing** — computed_fields get stub expressions as placeholders
- **Backward compatibility** — scaffold output evolves, old contracts still load fine
- **Automated merge acceptance** — human reviews every heuristic suggestion
