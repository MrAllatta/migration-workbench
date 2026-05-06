# Workbook

Turns profiler outputs + bundle configuration into **schema contract** YAML (and optional `models.py`-style stubs) for **product repositories** to review and refine into real Django models.

## Purpose

`scaffold_workbook_schema` is an advisory codegen step — not a substitute for domain decisions in client repos.

## Command

```bash
python manage.py scaffold_workbook_schema \
  --bundle-config example_data/scaffold_workbook_bundle.example.json \
  --table-profile example_data/scaffold_workbook_table_profile.example.json \
  --out /tmp/schema-contract.yaml
```

Inputs are pull-bundle-style JSON (`tabs[]`, `required_headers`) plus optional `profile_coda_doc` / `profile_coda_table` artifacts.

## Schema contract format (v1)

- **`version`** — required; currently `1.0`.
- **`source`** — informational metadata (may be null).
- **`tables[].bundle_worksheet_title`** / **`tables[].bundle_output_path`** — traceability to bundle tabs.
- **`tables[].columns[]`** — ordered; required bundle headers first.

**Advisory fields** (human review required): `suggested_model_name`, `suggested_field_name`, `django_field_class`, `django_field_kwargs`, `notes`.

**Relations:** relation-like columns may emit `ForeignKey` with `django_field_kwargs.to: TODO_TargetModel` until product repos choose real targets.

## View manifest

`scaffold_view_manifest` is a sibling artifact builder — it produces a **first-draft** UI/workflow contract from the profiler `structure.json` (emitted by `pull_bundle --include-structure`) and an optional schema-contract YAML.

```bash
python manage.py scaffold_view_manifest \
  --structure build/structure.json \
  --schema-contract build/schema-contract.yaml \
  --out build/view-manifest.yaml \
  --summary-json build/view-manifest.summary.json
```

Inputs are the structure artifact (required) and the schema contract (optional, used to bind each view to a model and reuse its `suggested_field_name` slugs).

### Schema (`view-manifest-draft-1`)

- **`views[].name`** / **`source_tab`** — slugified tab name and original tab title.
- **`views[].entity`** — bound `suggested_model_name` from the schema contract, or `null` until the operator decides.
- **`views[].type`** — defaults to `list`; operator picks `form` / `detail` / `dashboard` during discovery.
- **`views[].editable_fields`** / **`computed_fields`** — partitioned by the column's `is_formula` flag.
- **`views[].filterable_by`** — columns with a `data_validation_type` (dropdowns, ranges).
- **`views[].status_field`** — first dropdown-validated column whose header is `status` / `state` / `stage` (case-insensitive); `null` otherwise.
- **`workflow_hints.tab_sequence`** — visible tabs in `tab_position` order.
- **`workflow_hints.role_hints`** / **`weekly_actions`** — empty placeholders filled during the operator discovery interview.

The manifest is intended to be human-edited after generation. Treat the YAML as the source of truth once the operator has annotated it.

## Discovery interview

The discovery interview is the structured conversation a consultant runs with a client to fill in the placeholders the view manifest leaves blank: who owns each tab, what the status field actually means, and the 3-5 weekly actions the operator performs. It is split into two commands so the workflow stays auditable.

### Step 1 — generate the questionnaire

```bash
python manage.py generate_discovery_interview \
  --manifest build/view-manifest.yaml \
  --out build/discovery-interview.md
```

The output is hand-editable Markdown. Each answerable question is anchored by an HTML comment marker (`<!-- q: TYPE key=val -->`) so the parser can locate answers without matching free-form question prose. The operator either replaces each `> _Your answer:_` placeholder in place or appends a new blockquote line beneath it; both conventions are supported.

### Step 2 — merge the answers back

```bash
python manage.py merge_discovery_notes \
  --manifest build/view-manifest.yaml \
  --interview build/discovery-interview.md \
  --out build/view-manifest.yaml \
  --summary-out build/discovery-summary.md
```

Outputs:

- **Patched manifest** — `workflow_hints.role_hints`, `workflow_hints.weekly_actions`, and per-view `notes` are populated from the interview answers. Existing values are preserved and de-duplicated, so re-runs are additive.
- **Discovery summary** (optional) — a compact Markdown recap suitable to commit alongside the bundle as an audit artifact.

The same path may be used for `--manifest` and `--out` to overwrite in place; the manifest is fully read into memory before any write.

## Pointers

- [README](../README.md)
- [docs/schema-design-loop.md](../docs/schema-design-loop.md)
- Examples: [example_data/scaffold_workbook_bundle.example.json](../example_data/scaffold_workbook_bundle.example.json)
