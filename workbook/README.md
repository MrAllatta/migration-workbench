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

## Pointers

- [README](../README.md)
- [docs/schema-design-loop.md](../docs/schema-design-loop.md)
- Examples: [example_data/scaffold_workbook_bundle.example.json](../example_data/scaffold_workbook_bundle.example.json)
