# Design: Codegen Identifier Sanitization

**Date:** 2026-05-20
**Status:** Draft
**Scope:** `workbook/codegen/python_render.py`

---

## 1. Background

The schema contract stores original source column names (e.g., `"1"`, `"201_unit"`, `"yield"`). The codegen renders these directly into Python field declarations, producing invalid identifiers:

```python
1 = models.CharField(...)        # SyntaxError: invalid syntax
yield = models.CharField(...)   # SyntaxError: invalid syntax
201_unit = models.CharField(...) # SyntaxError: invalid syntax
```

The fix is codegen-level sanitization — the contract retains the original source name; the generated Python uses a valid identifier. No contract modification required.

---

## 2. Design

### 2.1 `to_python_identifier()` function

Add to `python_render.py`:

```python
import keyword
import re

def to_python_identifier(name: str) -> str:
    """Convert an arbitrary string to a valid Python identifier.

    Rules:
    1. Strip leading digits — prefix with ``f_``
    2. Replace invalid chars (anything not ``[a-zA-Z0-9_]``) with ``_``
    3. Collapse multiple underscores to one
    4. If result is a Python keyword, append ``_``
    5. If result is empty or starts with digit, prepend ``f_``
    6. Strip trailing underscores

    Examples:
        "1"          -> "f_1"
        "201_unit"   -> "f_201_unit"
        "yield"      -> "yield_"
        "Column #1"  -> "column_1"
        "Field.name" -> "field_name"
        "unit-price" -> "unit_price"
    """
    s = str(name)

    if s.isidentifier():
        if keyword.iskeyword(s):
            return f"{s}_"
        return s

    s = re.sub(r"[^a-zA-Z0-9_]", "_", s)
    s = re.sub(r"_+/g", "_", s)
    s = s.strip("_")

    if not s or s[0].isdigit():
        s = f"f_{s}"

    if keyword.iskeyword(s):
        s = f"{s}_"

    return s
```

### 2.2 Call sites

**`render_field()`** — sanitize field name before emitting:

```python
# Before:
return f"{pad}{name} = {field_class}({body})"

# After:
safe_name = to_python_identifier(name)
return f"{pad}{safe_name} = {field_class}({body})"
```

**`render_computed_property()`** — sanitize property name:

```python
# Before:
lines.append(f"{pad}def {name}(self) -> {return_type}:")

# After:
safe_name = to_python_identifier(name)
lines.append(f"{pad}def {safe_name}(self) -> {return_type}:")
```

Both call sites already use `name` as a string argument — no interface change needed.

### 2.3 Compatibility notes

- The contract YAML remains the source of truth. `suggested_field_name` keeps the original name. Only the generated Python is sanitized.
- Admin generator reads field names from `get_fields()` in `contract.py`. It does NOT need changes — admin uses the same names that the model generator uses, and both will now use the sanitized version.
- The import generator reads field names from `get_fields()` in `contract.py` — same behavior.

### 2.4 Edge cases

| Input | Output | Note |
|---|---|---|
| `"1"` | `"f_1"` | Leading digit stripped, prefix added |
| `"201_unit"` | `"f_201_unit"` | Leading digit stripped |
| `"yield"` | `"yield_"` | Python keyword, `_` appended |
| `"Column #1"` | `"column_1"` | Special char replaced, collapsed |
| `"Field.name"` | `"field_name"` | Period replaced |
| `"unit-price"` | `"unit_price"` | Dash replaced |
| `"_hidden"` | `"hidden"` | Leading underscore stripped by `strip("_")` |
| `"if"` | `"if_"` | Keyword |
| `""` | `"f_"` | Empty → fallback |
| `"_1_2_3_"` | `"f_1_2_3"` | Trailing/leading stripped, leading digit handled |

---

## 3. Testing Strategy

Add unit tests in `workbook/codegen/tests/test_python_render.py` (create if not exists):

```python
import pytest
from workbook.codegen.python_render import to_python_identifier

@pytest.mark.parametrize("input,expected", [
    ("1", "f_1"),
    ("201_unit", "f_201_unit"),
    ("yield", "yield_"),
    ("Column #1", "column_1"),
    ("Field.name", "field_name"),
    ("unit-price", "unit_price"),
    ("_hidden", "hidden"),
    ("if", "if_"),
    ("", "f_"),
    ("_1_2_3_", "f_1_2_3"),
    ("normal_field", "normal_field"),
    ("status", "status"),
])
def test_to_python_identifier(input, expected):
    assert to_python_identifier(input) == expected
```

Integration test: verify `models_auto.py` from a prior run now imports without error. If the file exists, run `python -c "import models_auto"` as part of test setup.

---

## 4. Rollout

1. Add `to_python_identifier()` to `python_render.py`
2. Update `render_field()` and `render_computed_property()` to call it
3. Add unit tests
4. Run `ruff check workbook/codegen/python_render.py`
5. If `models_auto.py` from prior run exists, verify it imports: `python -c "import models"`
6. Commit with message: "Codegen: sanitize field names to valid Python identifiers"

---

## 5. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Sanitized name collides with existing field | `to_python_identifier` handles `_` replacement; collapse prevents `field__name` → `field_name` collision. If collision still occurs, it's a pre-existing schema design issue. |
| Admin generator uses unsanitized names | Admin reads from `get_fields()` which returns contract names; both codegen paths sanitize at render time, so they're consistent. |
| Existing `models_auto.py` breaks after edit | Regeneration will produce sanitized names. Hand edits using original names will break — document the change in generated file header. |