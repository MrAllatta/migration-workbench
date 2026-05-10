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

- `**version**` — required; currently `1.0`.
- `**source**` — informational metadata (may be null).
- `**tables[].bundle_worksheet_title**` / `**tables[].bundle_output_path**` — traceability to bundle tabs.
- `**tables[].columns[]**` — ordered; required bundle headers first.

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

- `**views[].name**` / `**source_tab**` — slugified tab name and original tab title.
- `**views[].entity**` — bound `suggested_model_name` from the schema contract, or `null` until the operator decides.
- `**views[].type**` — defaults to `list`; operator picks `form` / `detail` / `dashboard` during discovery.
- `**views[].editable_fields**` / `**computed_fields**` — partitioned by the column's `is_formula` flag.
- `**views[].filterable_by**` — columns with a `data_validation_type` (dropdowns, ranges).
- `**views[].status_field**` — first dropdown-validated column whose header is `status` / `state` / `stage` (case-insensitive); `null` otherwise.
- `**workflow_hints.tab_sequence**` — visible tabs in `tab_position` order.
- `**workflow_hints.role_hints**` / `**weekly_actions**` — empty placeholders filled during the operator discovery interview.

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

## Codegen: generate_models

``generate_models`` reads a **hardened** schema-contract YAML (v1.0 or v1.1) and
writes a complete Django ``models.py`` with resolved foreign keys, ``class Meta``,
``__str__`` methods, and optional hand-authored extra fields.

```bash
python manage.py generate_models \
  --contract build/schema-contract.yaml \
  --out backend/apps/core/models.py \
  --app-label core
```

### Contract version 1.1 (hardened)

A v1.1 contract extends the auto-generated v1.0 format with hand-edited blocks.
Start from a v1.0 file produced by ``scaffold_workbook_schema``, then add:

```yaml
tables:
  - suggested_model_name: crop
    # --- v1.1 additions below ---
    model_meta:
      verbose_name: "Crop"
      verbose_name_plural: "Crops"
      ordering: ["name"]
    str_template: "{self.name}"
    # Resolve FK targets that were TODO_TargetModel
    fk_resolutions:
      crop: "Crop"
    # Override auto-inferred field types / kwargs
    field_overrides:
      crop_type:
        class: "CharField"
        kwargs:
          max_length: 100
          blank: true
          default: ""
    # Hand-authored fields not from any source column
    extra_fields:
      slug:
        class: "SlugField"
        kwargs:
          max_length: 200
          unique: true
          blank: true
```

The generator works with both v1.0 (auto-inferred only) and v1.1 (hardened)
contracts. v1.0 output is equivalent to the old ``--models-stub-out`` flag —
useful as a starting point but missing FK resolution and rich Meta.

### File safety

- Use ``--force`` to overwrite without prompting.
- The output file is **hand-editable** after generation; the header comment
  marks it as codegen-originated.  Re-running without ``--force`` on an
  existing file exits with a warning to prevent accidental overwrites.

## Codegen: generate_admin

``generate_admin`` reads a schema-contract YAML and an optional annotated
view-manifest YAML, then writes a complete Django ``admin.py`` with
``ModelAdmin`` registrations and ``TabularInline`` classes for reverse FK
relationships.

```bash
python manage.py generate_admin \
  --contract build/schema-contract.yaml \
  --manifest build/view-manifest.yaml \
  --out backend/apps/core/admin.py \
  --app-label core
```

### What it produces

- ``@admin.register`` for every model in the contract.
- ``list_display`` from the manifest's ``editable_fields`` (up to 5).
- ``list_filter`` from the manifest's ``filterable_by`` (dropdown-validated
  columns).
- ``search_fields`` from text-type fields (CharField, TextField, etc.) and
  FK name fields.
- ``readonly_fields`` from the manifest's ``computed_fields`` (formula
  columns).
- ``TabularInline`` classes for every reverse FK relationship discovered
  in the contract.
- Minimal ``ModelAdmin`` for every model even without a manifest — you
  get a registered admin shell to fill in.

### Discovery annotation

Run the discovery interview workflow first to annotate the view manifest
with operator context (role hints, status semantics, access notes).  The
admin generator reads the **annotated** manifest, so those answers can
inform the generated admin (e.g. which fields are editable in forms).

---

## Codegen: generate_import

``generate_import`` reads a v1.1 schema-contract with ``import_config``
blocks and writes a ``BaseImportCommand`` subclass that imports data from
normalized bundle CSVs.

```bash
python manage.py generate_import \
  --contract build/schema-contract.yaml \
  --out backend/apps/core/management/commands/import_core_data.py \
  --app-label core
```

### Contract extension: ``import_config``

Add an ``import_config`` block to each table in your v1.1 contract that
should be importable from a bundle CSV:

```yaml
tables:
  - suggested_model_name: crop
    columns: [ ... ]
    import_config:
      tier: 1                              # import order (lower = first)
      bundle_path: "reference/crop_info.csv"
      required_headers: [Crop, Type]
      aliases:                              # optional
        Type: [Crop Type, Variety]
      column_map:                           # optional; field → source header
        name: Crop
        crop_type: Type
      default_values:                       # optional
        crop_type: ""
      unique_on: [name]                     # fields for update_or_create
      required_source_columns: [name]       # must be non-empty
      fk_lookup:                            # FK resolution strategy
        crop:
          model: Crop                       # target model class
          on: name                          # field on target to match
      field_parsers:                        # optional override per field
        plant_date: parse_date

  - suggested_model_name: planting
    columns: [ ... ]
    import_config:
      tier: 2
      bundle_path: "year_2025/crop_planner.csv"
      required_headers: [Crop, Plant Date, Beds Used]
      column_map:
        crop: Crop
        plant_date: Plant Date
        beds_used: Beds Used
      unique_on: [crop, plant_date]
      required_source_columns: [crop]
      fk_lookup:
        crop:
          model: Crop
          on: name
```

### What it produces

A ``BaseImportCommand`` subclass with:

- ``_run_import_pipeline`` calling ``self.tier()`` for each tier group.
- One ``_import_<model>()`` method per table with ``import_config``.
- ``read_bundle_tab`` calls with alias-aware header detection and column
  mapping.
- Required-source-column guards (``record_missing_required``).
- FK resolution via ``_resolve_fk_by_text`` (``record_stale_fk`` on miss).
- Type-coerced field assignments (dates via ``_parse_date``, decimals via
  ``_dec``, ints via ``_int``, strings via ``.strip()``).
- ``write_disabled`` guard for dry-run mode.
- ``update_or_create`` with the configured ``unique_on`` fields.
- Per-model stats tracking (``self.stats["Model"]["created"/"updated"]``).

### Field parser inference

If no explicit ``field_parsers`` override is given, the generator infers
the parser from the Django field class in the contract:

| Contract field class | Generated parser |
|---|---|
| ``DateField`` / ``DateTimeField`` | ``self._parse_date()`` |
| ``DecimalField`` / ``FloatField`` | ``self._dec()`` |
| ``IntegerField`` / ``SmallIntegerField`` etc. | ``self._int()`` |
| ``BooleanField`` | ``row.get(...).lower() in ("yes", "true", "1")`` |
| ``CharField`` / ``TextField`` / others | ``row.get(...).strip()`` |

### File safety

All three ``generate_*`` commands share the same safety protocol: output
file exists and ``--force`` is not set → exit with a warning.  Generated
files are marked with a header comment indicating they came from the
codegen pipeline.

## Pointers

- [README](../README.md)
- [docs/schema-design-loop.md](../docs/schema-design-loop.md)
- Examples: [example_data/scaffold_workbook_bundle.example.json](../example_data/scaffold_workbook_bundle.example.json)

