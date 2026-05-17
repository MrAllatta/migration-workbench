# View Manifest Reference

> **Artifact:** `build/view-manifest.yaml`
> **Generator:** `python manage.py scaffold_view_manifest`
> **Version:** `view-manifest-draft-1`

A view manifest captures **UI and workflow** concerns for each spreadsheet tab
mapped to a Django admin view. It is a sibling to the schema contract.

## Top-Level Structure

```yaml
version: view-manifest-draft-1
generated_from:
  structure: profiler-output/structure.json
  contract: build/schema-contract.yaml
views:
  - entity: crop_plan_entry
    worksheet_title: Crop Planner
    label: Crop Plan Entry
    status_field: status
    status_values:
      - Planted
      - Growing
      - Harvested
    time_scope:
      year_field: source_bundle_year
      week_field: plan_week
      date_field: planting_date
      default_scope: current_season
    filterable_by:
      - source_bundle_year
      - status
    editable_fields:
      - crop
      - quantity
      - planting_date
    computed_fields:
      - total_cost
```

## Keys

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `version` | yes | string | Always `view-manifest-draft-1` |
| `generated_from` | yes | object | Source artifacts used to build this manifest |
| `views` | yes | array | One entry per spreadsheet tab |

### View Entry Keys

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `entity` | yes | string | Lowercase snake_case model name matching the contract |
| `worksheet_title` | yes | string | The spreadsheet tab title |
| `label` | no | string | Human-readable label for the admin UI |
| `status_field` | no | string | Column that tracks workflow state |
| `status_values` | no | array | Distinct values for the status field; used to generate admin actions |
| `time_scope` | no | object | Temporal field configuration |
| `filterable_by` | no | array | Columns usable as admin list filters |
| `editable_fields` | no | array | Columns editable in the admin change form |
| `computed_fields` | no | array | Columns that are read-only (spreadsheet formulas) |

### time_scope Keys

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `year_field` | no | string | Column containing the bundle year (e.g. `source_bundle_year`) |
| `week_field` | no | string | Integer column for week number |
| `date_field` | no | string | Date/DateTime column for drill-down navigation |
| `default_scope` | yes | string | Default temporal filter (currently always `current_season`) |

## Admin Generation Effects

When used with `generate_admin`, the view manifest controls:

- `list_display` — from `editable_fields` (up to 5)
- `list_filter` — from `filterable_by`; `status_field` is promoted to first position
- `search_fields` — auto-detected text columns; FK fields get `field__name` notation
- `readonly_fields` — from `computed_fields`
- `date_hierarchy` — from `time_scope.date_field`
- `get_queryset` override — when `time_scope.year_field` is set, filters by current year
- `@admin.action` methods — one per `status_values` entry
- FK link display methods — FK columns in `list_display` become clickable links
