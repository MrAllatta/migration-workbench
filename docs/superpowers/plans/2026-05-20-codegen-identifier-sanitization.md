# Codegen Identifier Sanitization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `to_python_identifier()` to codegen that sanitizes arbitrary source column names into valid Python identifiers, used both for field emission and as contract keys for kwargs lookup.

**Architecture:** A pure function in `python_render.py` handles sanitization. It's called at the start of `render_field()` and `render_computed_property()`. The sanitized name becomes the Python attribute name AND the key for kwargs lookup — kwargs are indexed by the sanitized name before rendering.

**Tech Stack:** Python stdlib (`re`, `keyword`), Django model field rendering.

---

## File Structure

- **Modify:** `workbook/codegen/python_render.py` — add `to_python_identifier()`, update `render_field()` kwargs lookup and emission, update `render_computed_property()` emission
- **Create:** `workbook/codegen/tests/test_python_render.py` — unit tests for `to_python_identifier()` and integration test verifying `models_auto.py` imports

---

## Task 1: Add `to_python_identifier()` to `python_render.py`

**Files:**
- Modify: `workbook/codegen/python_render.py:1-281`

- [ ] **Step 1: Write the failing test**

Create `workbook/codegen/tests/test_python_render.py`:

```python
"""Tests for python_render utilities."""

from __future__ import annotations

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
    ("Yield", "Yield_"),
    ("class", "class_"),
    ("1field", "f_1field"),
    ("Field  1", "field_1"),
    ("a..b", "a_b"),
    ("__dunder__", "dunder_"),
])
def test_to_python_identifier(input, expected):
    assert to_python_identifier(input) == expected


@pytest.mark.parametrize("keyword", [
    "False", "None", "True", "and", "as", "assert", "async", "await",
    "break", "class", "continue", "def", "del", "elif", "else", "except",
    "finally", "for", "from", "global", "if", "import", "in", "is",
    "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
    "while", "with", "yield",
])
def test_python_keywords_get_underscore_suffix(keyword):
    result = to_python_identifier(keyword)
    assert result.endswith("_")
    assert result.isidentifier()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest workbook/codegen/tests/test_python_render.py -v`
Expected: FAIL with `ImportError: cannot import name 'to_python_identifier' from 'workbook.codegen.python_render'`

- [ ] **Step 3: Add `to_python_identifier()` function to `python_render.py`**

Add import at top and function before `render_choices_class`:

```python
import keyword
import re


def to_python_identifier(name: str) -> str:
    """Convert an arbitrary string to a valid Python identifier.

    Rules:
    1. If already valid and not a keyword, return as-is.
    2. Replace invalid chars (anything not [a-zA-Z0-9_]) with underscore.
    3. Collapse multiple consecutive underscores to one.
    4. Strip leading and trailing underscores.
    5. Prepend 'f_' if empty or starts with a digit.
    6. Append '_' if it is a Python keyword.
    """
    s = str(name)

    if s.isidentifier() and not keyword.iskeyword(s):
        return s

    s = re.sub(r"[^a-zA-Z0-9_]", "_", s)
    s = re.sub(r"_+/g", "_", s)
    s = s.strip("_")

    if not s or s[0].isdigit():
        s = f"f_{s}" if s else "f_"

    if keyword.iskeyword(s):
        s = f"{s}_"

    return s
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest workbook/codegen/tests/test_python_render.py -v`
Expected: PASS

- [ ] **Step 5: Run linter**

Run: `ruff check workbook/codegen/python_render.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add workbook/codegen/python_render.py workbook/codegen/tests/test_python_render.py
git commit -m "feat: add to_python_identifier() for codegen sanitization"
```

---

## Task 2: Update `render_field()` to use sanitized name as kwargs key

**Files:**
- Modify: `workbook/codegen/python_render.py:77-131`

The sanitized name replaces the original name in:
1. The Python attribute declaration (`name = models.CharField(...)`)
2. The kwargs dict lookup — kwargs indexed by sanitized name

- [ ] **Step 1: Write the failing integration test**

Add to `workbook/codegen/tests/test_python_render.py`:

```python
def test_render_field_sanitizes_name_and_looks_up_kwargs_by_sanitized_name():
    """Sanitized name is used both for attribute emission and kwargs lookup."""
    from workbook.codegen.python_render import render_field

    # Source column "1" maps to sanitized "f_1".
    # kwargs dict is keyed by sanitized name "f_1".
    result = render_field(
        name="1",
        field_class="models.CharField",
        kwargs={
            "max_length": 100,
            "null": True,
        },
    )
    assert "f_1 = models.CharField" in result
    assert "max_length=100" in result

    # Keyword name "yield" -> "yield_"
    result2 = render_field(
        name="yield",
        field_class="models.CharField",
        kwargs={
            "max_length": 50,
        },
    )
    assert "yield_ = models.CharField" in result2
    assert "max_length=50" in result2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest workbook/codegen/tests/test_python_render.py::test_render_field_sanitizes_name_and_looks_up_kwargs_by_sanitized_name -v`
Expected: FAIL (name not sanitized in output)

- [ ] **Step 3: Update `render_field()`**

Replace the function body with:

```python
def render_field(
    name: str,
    field_class: str,
    kwargs: dict[str, Any],
    indent: int = 4,
    enum_names: set[str] | None = None,
    model_name: str | None = None,
    rendered_model_names: set[str] | None = None,
) -> str:
    """Render a single Django model field declaration.

    Args:
        name: Field name (e.g. ``"crop"``).
        field_class: Fully-qualified Django field class (e.g. ``"models.ForeignKey"``).
        kwargs: Keyword arguments for the field constructor, keyed by sanitized
            Python identifier (e.g. ``"f_1"`` not ``"1"``).
        indent: Spaces of indentation (default 4).
        enum_names: Set of known enum type names (passed to *render_field_kwargs*).
        model_name: The Django model class name (for enum references).
        rendered_model_names: Set of already-rendered model names; used to
            detect forward references that need quoting.

    Returns:
        Indented field declaration line::

            name = models.CharField(max_length=200, unique=True)
    """
    pad = " " * indent
    safe_name = to_python_identifier(name)

    if field_class == "models.ForeignKey":
        remaining = dict(kwargs)
        to_val = remaining.pop("to", None)
        kw_str = render_field_kwargs(remaining, enum_names, model_name)
        if to_val is not None:
            if isinstance(to_val, str) and to_val == "self":
                to_str = '"self"'
            elif (
                isinstance(to_val, str)
                and to_val.isidentifier()
                and rendered_model_names is not None
                and to_val not in rendered_model_names
            ):
                to_str = repr(to_val)
            elif isinstance(to_val, str) and to_val.isidentifier():
                to_str = to_val
            else:
                to_str = repr(to_val)
            body = f"{to_str}, {kw_str}" if kw_str else to_str
        else:
            body = kw_str
    else:
        body = render_field_kwargs(kwargs, enum_names, model_name)

    if body:
        return f"{pad}{safe_name} = {field_class}({body})"
    return f"{pad}{safe_name} = {field_class}()"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest workbook/codegen/tests/test_python_render.py::test_render_field_sanitizes_name_and_looks_up_kwargs_by_sanitized_name -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest workbook/codegen/tests/ -v`
Expected: all pass

- [ ] **Step 6: Run linter**

Run: `ruff check workbook/codegen/python_render.py`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add workbook/codegen/python_render.py workbook/codegen/tests/test_python_render.py
git commit -m "feat: render_field uses sanitized name for attribute and kwargs key"
```

---

## Task 3: Update `render_computed_property()` to sanitize property name

**Files:**
- Modify: `workbook/codegen/python_render.py:160-191`

- [ ] **Step 1: Add test for computed property sanitization**

Add to `workbook/codegen/tests/test_python_render.py`:

```python
def test_render_computed_property_sanitizes_name():
    from workbook.codegen.python_render import render_computed_property

    result = render_computed_property(name="201_value", return_type="int")
    assert "def f_201_value(self) -> int:" in result

    result2 = render_computed_property(name="class")
    assert "def class_(self):" in result2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest workbook/codegen/tests/test_python_render.py::test_render_computed_property_sanitizes_name -v`
Expected: FAIL

- [ ] **Step 3: Update `render_computed_property()`**

Replace the function body with:

```python
def render_computed_property(
    name: str,
    return_type: str | None = None,
    expression: str | None = None,
    indent: int = 4,
) -> str:
    """Render a ``@property`` method from a computed field definition.

    Args:
        name: Property name (e.g. ``"signed_quantity"``).
        return_type: Optional return type annotation.
        expression: Python source for the property body.  When ``None``,
            renders a stub with ``...``.
        indent: Spaces of indentation (default 4).

    Returns:
        Property method source block.
    """
    pad = " " * indent
    safe_name = to_python_identifier(name)
    lines: list[str] = []
    lines.append(f"{pad}@property")
    if return_type:
        lines.append(f"{pad}def {safe_name}(self) -> {return_type}:")
    else:
        lines.append(f"{pad}def {safe_name}(self):")
    if expression:
        for line in expression.strip().split("\n"):
            lines.append(f"{pad * 2}{line}")
    else:
        lines.append(f"{pad * 2}...")
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest workbook/codegen/tests/test_python_render.py::test_render_computed_property_sanitizes_name -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest workbook/codegen/tests/ -v`
Expected: all pass

- [ ] **Step 6: Run linter**

Run: `ruff check workbook/codegen/python_render.py`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add workbook/codegen/python_render.py
git commit -m "feat: render_computed_property sanitizes property name"
```

---

## Task 4: Verify end-to-end with generated `models_auto.py`

- [ ] **Step 1: Find any existing `models_auto.py` in the workspace**

Run: `find . -name "models_auto.py" -not -path "./.git/*" 2>/dev/null`
If none found, skip to step 4.

- [ ] **Step 2: Check if it imports cleanly**

Run: `python -c "import sys; sys.path.insert(0, '.'); exec(open('./path/to/models_auto.py').read())"`
Expected: no SyntaxError. If it has invalid field names like `1 =` or `yield =`, the test will show the pre-existing issue.

- [ ] **Step 3: Regenerate models from the contract**

Run: `python manage.py generate_models --force --app-label workbook`
Then re-run the import check. Expected: clean import.

- [ ] **Step 4: Run full codegen test suite**

Run: `pytest workbook/ -v --tb=short`
Expected: all pass, no regressions in admin_generator, import_generator, model_generator.

- [ ] **Step 5: Run chassis gate**

Run: `make chassis-gate` (or equivalent)
Expected: all checks pass

---

## Verification Checklist

- [ ] `to_python_identifier` is tested with all documented edge cases
- [ ] `render_field` sanitizes name and uses it for both emission and kwargs key
- [ ] `render_computed_property` sanitizes name
- [ ] `ruff check` passes on modified files
- [ ] Existing codegen tests still pass (no regressions)
- [ ] Generated `models_auto.py` imports cleanly