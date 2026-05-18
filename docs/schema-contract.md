# Schema Contract

## Introduction

A **schema contract** is a YAML document that captures the mapping from spreadsheet tabs to Django models. It sits at the centre of the codegen pipeline:

```
profile → contract → harden → generate_models
              ↓
         generate_admin
              ↓
         generate_import
```

1. **Profile** — `profile_tab` / `scan_formula_patterns` produces column metadata.
2. **Contract** — `scaffold_workbook_schema` merges bundle config + profiler output into a YAML schema contract.
 3. **Harden** — A human edits the auto-generated output, adding `model_meta`, `fk_resolutions`, `field_overrides`, `extra_fields`, `import_config`, `computed_fields`, and `admin` blocks.
4. **Generate** — `generate_models`, `generate_admin`, and `generate_import` consume the hardened contract to produce `models.py`, `admin.py`, and import commands.

For the command reference see [`workbook/README.md`](../workbook/README.md).



## Top-level structure

```yaml
source:                           # informational metadata
  provider: "google_sheets"
  doc_url: "https://..."
  doc_id: "abc123"
  source_id: "my_project"

enums:                            # enum definitions for choices
  EventType:
    - [seeded, "Seeded"]
    - [harvested, "Harvested"]

tables: []                        # list of model definitions (see below)
```

### `!include` composition

Contract files can be split across multiple YAML files using the `!include` and `!include_list` tags:

```yaml
tables:
  - suggested_model_name: crop
    columns: []
  - !include_list tables/crop_models.yaml    # inlines a YAML list
```

- Include paths are resolved **relative to the including file's directory**.
- Nested includes work (relative to the file that contains the `!include` directive).
- **Cyclic includes are detected and rejected** with a `ValueError` listing the cycle path.
- `!include_list` requires the target file to contain a YAML list; a non-list produces an error.

---

## Model definition

Each entry in the `tables` list is a mapping with the following keys.

### `table_name`

The Django `db_table` value. When set in `model_meta.db_table`, that value is used; otherwise the default is `{app_label}_{suggested_model_name}`.

```yaml
model_meta:
  db_table: "my_custom_table"
```

### `app_label`

The Django app label for the model. Set via `model_meta.app_label`. Falls back to the `--app-label` CLI argument.

```yaml
model_meta:
  app_label: "inventory"
```

### `model_name`

PascalCase model class name. Used by designed models that have no source tab; otherwise derived from `suggested_model_name`.

```yaml
model_name: "FieldEvent"
```

### `source_tab`

Override for the source tab name. When set to `null`, the model has no source-tab association (a "designed model").

```yaml
source_tab: null
```

### `fields` — via `columns[]`

The primary field list. Each column maps to a Django model field:

```yaml
columns:
  - source_column: "Crop"                        # original spreadsheet header
    suggested_field_name: "name"                  # snake_case Django field name
    profiler_format_type: "text"                  # inferred from profiler
    has_formula: false
    formula_pattern: null
    django_field_class: "models.CharField"        # Django field class
    django_field_kwargs:                          # constructor kwargs
      max_length: 200
      unique: true
    notes: []                                     # advisory strings
```

### `computed_fields`

Fields rendered as `@property` methods instead of database columns. Each key is the property name:

```yaml
computed_fields:
  signed_quantity:
    return_type: int
    expression: "self.quantity * -1 if self.direction == 'out' else self.quantity"
  full_name:
    return_type: str
    expression: "f'{self.first_name} {self.last_name}'"
```

### `model_meta`

Django `class Meta` options:

```yaml
model_meta:
  verbose_name: "Crop"
  verbose_name_plural: "Crops"
  ordering: ["name"]                  # default ordering
  unique_together:                    #
    - [crop, plant_date]
  constraints: []                     # — list of constraint dicts
  indexes: []                         # — list of index dicts
  db_table: "my_table"               # explicit table name
  app_label: "core"                  # per-model app override
```

### `admin`

Configuration for the generated `admin.py`:

```yaml
admin:
  list_display: ["name", "crop_type", "plant_date"]
  list_filter: ["crop_type", "status"]
  search_fields: ["name", "notes"]
  autocomplete_fields: ["crop"]      # FK fields with autocomplete
  list_editable: ["crop_type"]       # inline-editable columns
  readonly_fields: ["computed"]      # excluded from forms
  inlines: ["Planting"]              # reverse FK inline model names
```

### `import_config`

Configuration for data import via `BaseImportCommand` subclasses:

```yaml
import_config:
  tier: 1                                    # import order (lower = first)
  bundle_path: "reference/crop_info.csv"      # CSV path relative to bundle root
  required_headers: ["Crop", "Type"]          # headers the CSV must contain
  aliases:                                    # header alias map
    Type: ["Crop Type", "Variety"]
  column_map:                                 # field → source header
    name: Crop
    crop_type: Type
  field_parsers:                              # explicit parser per field
    plant_date: parse_date
  field_transforms:                           # lambda for multi-source fields
    full_name: "' '.join(p for p in parts if p)"
  default_values:                             # fallback defaults
    crop_type: ""
  unique_on: ["name"]                         # fields for update_or_create
  required_source_columns: ["name"]           # must be non-empty
  fk_lookup:                                  # FK resolution strategy
    crop:
      model: Crop                             # target model class
      on: name                                # field on target to match
```

### `is_abstract`

When `true`, the model is rendered as an abstract base (`class Meta: abstract = True`). No migration is created.

```yaml
is_abstract: true
```

### Additional table-level keys

| Key | Description |
|-----|-------------|
| `bundle_worksheet_title` | Source worksheet tab name |
| `bundle_output_path` | Bundle output CSV path |
| `suggested_model_name` | Snake_case model name |
| `str_template` | `__str__` f-string body, e.g. `"{self.name}"` |
| `fk_resolutions` | `{field_name: target_model}` FK target overrides |
| `field_overrides` | Per-field class/kwarg overrides |
| `extra_fields` | Hand-authored fields not from any column |
| `model_base` | Model base class, defaults to `"models.Model"` |
| `extra_imports` | Extra import lines for non-standard bases |
| `hooks` | Code injection points: `after_model`, `after_meta`, `before_return` |
| `suppress_review_warnings` | List of `rule_id` strings to silence in `review_contract` |
| `import_key` | Auto-suggested import key `{fields, confidence, note}` |

---

## Field types

### `CharField`

```yaml
django_field_class: "models.CharField"
django_field_kwargs:
  max_length: 200       # required (recommended)
  unique: true
  blank: true
  null: true
  default: ""
  choices: EventType    # bare enum name
```

### `IntegerField`

```yaml
django_field_class: "models.IntegerField"
django_field_kwargs:
  null: true
  blank: true
  default: 0
  unique: true
```

Also supported: `PositiveIntegerField`, `PositiveSmallIntegerField`, `SmallIntegerField`, `BigIntegerField`.

### `BooleanField`

```yaml
django_field_class: "models.BooleanField"
django_field_kwargs:
  null: true
  blank: true
  default: false
```

### `DateField`

```yaml
django_field_class: "models.DateField"
django_field_kwargs:
  null: true
  blank: true
  auto_now: true        # set to now on every save
  auto_now_add: true    # set to now on creation only
```

### `DateTimeField`

```yaml
django_field_class: "models.DateTimeField"
django_field_kwargs:
  null: true
  blank: true
  auto_now: true
  auto_now_add: true
```

### `DecimalField`

```yaml
django_field_class: "models.DecimalField"
django_field_kwargs:
  max_digits: 10        # required
  decimal_places: 2     # required
  null: true
  blank: true
  default: 0.0
  unique: true
```

### `ForeignKey`

```yaml
django_field_class: "models.ForeignKey"
django_field_kwargs:
  to: "Crop"                    # target model name
  on_delete: "models.PROTECT"   # or CASCADE, SET_NULL, etc.
  null: true
  blank: true
  related_name: "crops"         # optional reverse relation name
```

Auto-generated contracts use `"TODO_TargetModel"` as the `to` value; the human hardens it via `fk_resolutions`:

```yaml
fk_resolutions:
  crop: "Crop"
```

### `ManyToManyField`

```yaml
django_field_class: "models.ManyToManyField"
django_field_kwargs:
  to: "Crop"
  blank: true
  related_name: "fields"
```

### `TextField`

```yaml
django_field_class: "models.TextField"
django_field_kwargs:
  blank: true
  null: true
  default: ""
```

---

## `computed_fields`

Computed fields are rendered as `@property` methods in the generated model. They are excluded from import and admin forms.

```yaml
computed_fields:
  total_value:
    return_type: Decimal
    expression: "self.quantity * self.unit_price"
  is_overdue:
    return_type: bool
    expression: "self.due_date and self.due_date < date.today()"
  display_name:
    expression: "f'{self.first_name} {self.last_name}'"    # return_type is optional
```

Each entry produces:

```python
@property
def total_value(self) -> Decimal:
    return self.quantity * self.unit_price
```

---

## `model_meta`

All keys are passed through to Django's `class Meta`:

```yaml
model_meta:
  verbose_name: "Planting"
  verbose_name_plural: "Plantings"
  ordering: ["-plant_date"]                  # descending order
  unique_together:                           # multi-field uniqueness
    - [crop, plant_date]
    - [field, block, season]
  constraints:                               # arbitrary constraints

  indexes:                                   # explicit indexes
    - fields: [status]
      name: idx_planting_status
  db_table: "my_app_planting"               # explicit table name
  app_label: "my_app"                       # per-model app override
```

---

## Admin configuration

The `admin` block is consumed by `generate_admin` to produce `ModelAdmin` classes:

```yaml
admin:
  list_display:
    - name
    - crop_type
    - plant_date
  list_filter:
    - crop_type
    - status
  search_fields:
    - name
    - notes
  autocomplete_fields:       # FK fields rendered as autocomplete widgets
    - crop
  list_editable:             # fields editable directly in list view
    - crop_type
  readonly_fields:           # excluded from forms (often computed_fields)
    - total_value
  inlines:                   # reverse FK inline class names
    - Planting
```

When `model_base` is an `AbstractUser` subclass, `generate_admin` emits a `UserAdmin` subclass instead of `ModelAdmin`.

---

## `import_config`

Each table with an `import_config` block gets an `_import_<model>()` method in the generated import command.

```yaml
import_config:
  tier: 1                                # import ordering (lower = first)
  bundle_path: "reference/crop_info.csv"
  required_headers: ["Crop", "Type"]     # CSV must contain these
  aliases:                               # canonical → [alias, ...]
    Type: ["Crop Type", "Variety"]
  column_map:                            # field_name → source_header
    name: Crop
    crop_type: Type
  field_transforms:                      # lambda for multi-column sources
    full_name: "' '.join(p for p in parts if p)"
  field_parsers:                         # explicit parser override
    plant_date: parse_date
    quantity: int
  default_values:                        # fallback when CSV value is empty
    crop_type: ""
  unique_on: ["name"]                    # fields for update_or_create
  required_source_columns: ["name"]      # must be non-empty
  fk_lookup:                             # FK resolution strategy
    crop:
      model: Crop                        # target model class name
      on: name                           # field on target to match by text
  source_tab: "Custom Tab Name"          # override bundle_worksheet_title
```

### Parser inference

When `field_parsers` is not specified, the generator infers parsers from the Django field class:

| Contract field class | Generated parser |
|----------------------|------------------|
| `DateField` / `DateTimeField` | `self._parse_date()` |
| `DecimalField` / `FloatField` | `self._dec()` |
| `IntegerField` / `SmallIntegerField` etc. | `self._int()` |
| `BooleanField` | `self._bool()` |
| `CharField` / `TextField` / others | `row.get(...).strip()` |

### Multi-source column_map

When a `column_map` value is a list, the field is assembled from multiple source columns:

```yaml
column_map:
  full_name: ["First Name", "Last Name"]
```

This generates a `full_name_parts` collection and applies the `field_transforms` lambda (or a space-join by default).

---

## `!include` composition

### Syntax

| Tag | Target type | Behaviour |
|-----|-------------|-----------|
| `!include path` | Mapping | Inlines the mapping at the point of use |
| `!include_list path` | List | Splices the list entries into the parent list |

### Path resolution

Paths are resolved relative to the directory of the file that contains the `!include` directive, not the root contract file. Nested includes resolve relative to the including file's directory.

```
contracts/
├── main.yaml           # tables: [!include_list crop.yaml]
└── crop.yaml           # relative to main.yaml — correct
└── tables/
    ├── admin.yaml      # !include_list ../crop.yaml — back-reference
    └── crop.yaml       # !include_list crop.yaml — looks in tables/
                        # for nested tables/crop.yaml
```

### Cyclic-include detection

If a file includes itself (directly or transitively), `load_contract` raises a `ValueError` with the cycle path:

```
cyclic include detected: /tmp/cycle_first.yaml -> /tmp/cycle_second.yaml -> /tmp/cycle_first.yaml
```

---


