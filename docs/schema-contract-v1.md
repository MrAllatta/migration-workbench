# Schema Contract v1

The schema contract emitted by `scaffold_workbook_schema` is an advisory model-design artifact for product repositories.

## Stability

- `version` is required and currently `1.0`.
- `source` metadata fields are informational and may be null.
- `tables[].bundle_worksheet_title` and `tables[].bundle_output_path` are source-traceability fields.
- `tables[].columns[]` entries are ordered with required bundle headers first.

## Advisory fields

These values are generated hints and require human review:

- `suggested_model_name`
- `suggested_field_name`
- `django_field_class`
- `django_field_kwargs`
- `notes`

## Relation placeholders

When profiler metadata marks a column as relation-like, generated output intentionally uses a placeholder target:

- `django_field_class: models.ForeignKey`
- `django_field_kwargs.to: TODO_TargetModel`

This ensures generated stubs remain syntactically valid while requiring explicit target-model decisions in product repos.
