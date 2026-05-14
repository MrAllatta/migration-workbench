# Migration Safety Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `migration_safety_checks()` function and `wb contract safety` CLI to detect destructive migration risks from contract diffs.

**Architecture:** `migration_safety_checks(diffs)` interprets `diff_contracts()` output — no need to re-compare contracts. CLI handler in `wb_cli.py` renders text/JSON. TDD throughout.

**Tech Stack:** Python 3.12+, `argparse` for CLI, no new dependencies.

---

### Task 1: Write tests for `migration_safety_checks()`

**Files:**
- Create: `workbook/tests/test_migration_safety.py` (new file)
- Modify: (none)

- [ ] **Step 1: Write helper + test for field removed**

Create the test file:

```python
"""Tests for workbook.codegen.contract.migration_safety_checks."""

from __future__ import annotations

from workbook.codegen.contract import (
    MIGRATION_SEVERITY_DANGER,
    MIGRATION_SEVERITY_WARNING,
    migration_safety_checks,
)


def test_field_removed_is_danger():
    """Removing a field produces a DANGER-level warning."""
    diffs = {
        "model_diffs": {
            "Crop": {
                "fields_removed": [
                    {"name": "legacy_id", "class": "models.IntegerField",
                     "kwargs": {}},
                ],
            },
        },
    }
    results = migration_safety_checks(diffs)
    assert len(results) == 1
    assert results[0]["severity"] == MIGRATION_SEVERITY_DANGER
    assert results[0]["model"] == "Crop"
    assert results[0]["field"] == "legacy_id"
    assert "removed" in results[0]["message"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest workbook/tests/test_migration_safety.py::test_field_removed_is_danger -x --tb=short`
Expected: FAIL with `ImportError: cannot import name 'migration_safety_checks'`

- [ ] **Step 3: Write test for nullable→non-nullable**

```python
def test_nullable_becomes_non_nullable_is_danger():
    """A field losing null=True is a DANGER — migration fails if nulls exist."""
    diffs = {
        "model_diffs": {
            "Crop": {
                "fields_changed": [
                    {
                        "name": "name",
                        "class": {"old": "models.CharField", "new": "models.CharField"},
                        "kwargs": {
                            "null": {"old": True, "new": False},
                            "max_length": {"old": 100, "new": 200},
                        },
                    },
                ],
            },
        },
    }
    results = migration_safety_checks(diffs)
    assert len(results) >= 1
    danger = [r for r in results if r["severity"] == MIGRATION_SEVERITY_DANGER]
    assert any("null" in r["message"].lower() for r in danger)
    assert danger[0]["model"] == "Crop"
    assert danger[0]["field"] == "name"
```

- [ ] **Step 4: Write test for field class change**

```python
def test_field_class_changed_is_warning():
    """Changing a field's class type is a WARNING."""
    diffs = {
        "model_diffs": {
            "Crop": {
                "fields_changed": [
                    {
                        "name": "notes",
                        "class": {"old": "models.TextField", "new": "models.CharField"},
                        "kwargs": {"max_length": {"old": None, "new": 500}},
                    },
                ],
            },
        },
    }
    results = migration_safety_checks(diffs)
    assert len(results) >= 1
    warnings = [r for r in results if r["severity"] == MIGRATION_SEVERITY_WARNING]
    assert any("class" in r["message"].lower() or "type" in r["message"].lower()
               for r in warnings)
```

- [ ] **Step 5: Write test for max_length decreased**

```python
def test_max_length_decreased_is_warning():
    """Reducing max_length is a WARNING — truncation risk."""
    diffs = {
        "model_diffs": {
            "Crop": {
                "fields_changed": [
                    {
                        "name": "name",
                        "class": {"old": "models.CharField", "new": "models.CharField"},
                        "kwargs": {
                            "max_length": {"old": 200, "new": 100},
                        },
                    },
                ],
            },
        },
    }
    results = migration_safety_checks(diffs)
    assert len(results) >= 1
    warnings = [r for r in results if r["severity"] == MIGRATION_SEVERITY_WARNING]
    assert any("max_length" in r["message"] for r in warnings)
```

- [ ] **Step 6: Write test for unique=True added**

```python
def test_unique_added_is_warning():
    """Adding unique=True is a WARNING — migration fails if duplicates exist."""
    diffs = {
        "model_diffs": {
            "Crop": {
                "fields_changed": [
                    {
                        "name": "name",
                        "class": {"old": "models.CharField", "new": "models.CharField"},
                        "kwargs": {
                            "unique": {"old": None, "new": True},
                        },
                    },
                ],
            },
        },
    }
    results = migration_safety_checks(diffs)
    assert len(results) >= 1
    warnings = [r for r in results if r["severity"] == MIGRATION_SEVERITY_WARNING]
    assert any("unique" in r["message"].lower() for r in warnings)
```

- [ ] **Step 7: Write test for non-nullable field added without default**

```python
def test_non_nullable_field_added_without_default_is_warning():
    """Adding a non-nullable field without a default is a WARNING."""
    diffs = {
        "model_diffs": {
            "Crop": {
                "fields_added": [
                    {"name": "required_field", "class": "models.CharField",
                     "kwargs": {"max_length": 100}},
                ],
            },
        },
    }
    results = migration_safety_checks(diffs)
    assert len(results) >= 1
    warnings = [r for r in results if r["severity"] == MIGRATION_SEVERITY_WARNING]
    assert any("null" in r["message"].lower() or "default" in r["message"].lower()
               for r in warnings)
```

- [ ] **Step 8: Write test for no diffs = empty results**

```python
def test_no_diffs_returns_empty():
    """Empty diff produces no safety warnings."""
    assert migration_safety_checks({}) == []
    assert migration_safety_checks({"model_diffs": {}}) == []
```

- [ ] **Step 9: Run all tests to verify they fail**

Run: `python -m pytest workbook/tests/test_migration_safety.py -x --tb=short`
Expected: 8 tests, all fail with `ImportError`

---

### Task 2: Implement `migration_safety_checks()` in contract.py

**Files:**
- Modify: `workbook/codegen/contract.py` (add constants + function at end of file, after `diff_contracts`)

- [ ] **Step 1: Add constants and function**

Append to `workbook/codegen/contract.py` after the last function:

```python
MIGRATION_SEVERITY_DANGER = "DANGER"
MIGRATION_SEVERITY_WARNING = "WARNING"


def migration_safety_checks(diffs: dict[str, Any]) -> list[dict[str, Any]]:
    """Inspect ``diff_contracts()`` output for migration safety risks.

    Checks for field removals, nullable→non-nullable changes, field type
    changes, ``max_length`` reductions, ``unique=True`` additions, and
    non-nullable fields added without defaults.

    Args:
        diffs: Output from :func:`diff_contracts`.

    Returns:
        List of risk items, each with ``severity`` (DANGER or WARNING),
        ``model``, ``field``, ``message``, and optional ``detail``.
        Empty list when no risks are found.
    """
    results: list[dict[str, Any]] = []

    for model_name, model_diff in (diffs.get("model_diffs") or {}).items():
        # Field removals.
        for f in model_diff.get("fields_removed") or []:
            results.append({
                "severity": MIGRATION_SEVERITY_DANGER,
                "model": model_name,
                "field": f["name"],
                "message": "Field removed — existing data in source will be lost",
                "detail": {"old_class": f.get("class", "")},
            })

        # Field changes.
        for fc in model_diff.get("fields_changed") or []:
            fname = fc["name"]
            kwargs_diff = fc.get("kwargs") or {}

            # nullable → non-nullable
            null_old = kwargs_diff.get("null", {}).get("old")
            null_new = kwargs_diff.get("null", {}).get("new")
            if null_old is True and null_new is not True:
                results.append({
                    "severity": MIGRATION_SEVERITY_DANGER,
                    "model": model_name,
                    "field": fname,
                    "message": "Field changed from nullable to non-nullable — "
                    "migration will fail if null rows exist",
                    "detail": {"null": {"old": True, "new": null_new}},
                })

            # Field class changed
            class_change = fc.get("class")
            if class_change and class_change["old"] != class_change["new"]:
                results.append({
                    "severity": MIGRATION_SEVERITY_WARNING,
                    "model": model_name,
                    "field": fname,
                    "message": (
                        f"Field class changed: "
                        f"{_field_class_short(class_change['old'])} -> "
                        f"{_field_class_short(class_change['new'])}"
                        " — existing data may not cast cleanly"
                    ),
                    "detail": {"old_class": class_change["old"],
                               "new_class": class_change["new"]},
                })

            # max_length decreased
            max_old = kwargs_diff.get("max_length", {}).get("old")
            max_new = kwargs_diff.get("max_length", {}).get("new")
            if (max_old is not None and max_new is not None
                    and max_old > max_new):
                results.append({
                    "severity": MIGRATION_SEVERITY_WARNING,
                    "model": model_name,
                    "field": fname,
                    "message": (
                        f"max_length decreased: {max_old} -> {max_new}"
                        " — existing data may be truncated"
                    ),
                    "detail": {"old_max_length": max_old,
                               "new_max_length": max_new},
                })

            # unique=True added
            unique_old = kwargs_diff.get("unique", {}).get("old")
            unique_new = kwargs_diff.get("unique", {}).get("new")
            if unique_new is True and unique_old is not True:
                results.append({
                    "severity": MIGRATION_SEVERITY_WARNING,
                    "model": model_name,
                    "field": fname,
                    "message": (
                        "unique=True added — "
                        "migration will fail if duplicate values exist"
                    ),
                    "detail": {"unique": {"old": unique_old, "new": True}},
                })

        # Field additions — check non-nullable without default.
        for f in model_diff.get("fields_added") or []:
            kwargs = f.get("kwargs") or {}
            null = kwargs.get("null")
            has_default = (
                "default" in kwargs
                or null is True
            )
            if not has_default:
                results.append({
                    "severity": MIGRATION_SEVERITY_WARNING,
                    "model": model_name,
                    "field": f["name"],
                    "message": (
                        "Non-nullable field added without default — "
                        "existing rows will need a backfill value"
                    ),
                    "detail": {"class": f.get("class", "")},
                })

    return results
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest workbook/tests/test_migration_safety.py -x --tb=short`
Expected: 8 passed

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest --tb=short -q`
Expected: 238 passed

- [ ] **Step 4: Commit**

```bash
git add workbook/codegen/contract.py workbook/tests/test_migration_safety.py
git commit -m "feat: migration safety checks — migration_safety_checks() function"
```

---

### Task 3: Add CLI subcommand

**Files:**
- Modify: `deployment/wb_cli.py` (add `_contract_safety()` handler + parser wiring)

- [ ] **Step 1: Write tests for CLI**

Add to `workbook/tests/test_migration_safety.py`:

```python
# CLI integration


def test_contract_safety_cli_text(tmp_path, capsys):
    """CLI emits human-readable text by default."""
    from deployment.wb_cli import _contract_safety
    import argparse

    old_path = tmp_path / "old.yaml"
    new_path = tmp_path / "new.yaml"
    old_path.write_text("version: '1.1'\nsource: {}\ntables: []\n")
    new_path.write_text("version: '1.1'\nsource: {}\ntables: []\n")

    args = argparse.Namespace(
        old=str(old_path), new=str(new_path), json=False
    )
    rc = _contract_safety(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "safe" in captured.out.lower() or "no" in captured.out.lower()


def test_contract_safety_cli_json(tmp_path, capsys):
    """CLI emits JSON with --json flag."""
    from deployment.wb_cli import _contract_safety
    import argparse
    import json

    old_path = tmp_path / "old.yaml"
    new_path = tmp_path / "new.yaml"
    old_path.write_text("version: '1.1'\nsource: {}\ntables: []\n")
    new_path.write_text("version: '1.1'\nsource: {}\ntables: []\n")

    args = argparse.Namespace(
        old=str(old_path), new=str(new_path), json=True
    )
    rc = _contract_safety(args)
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
```

- [ ] **Step 2: Add `_contract_safety()` handler and parser wiring**

Add the handler function after `_contract_diff()` in `deployment/wb_cli.py`:

```python
def _contract_safety(args: argparse.Namespace) -> int:
    _setup_django()
    from workbook.codegen.contract import (
        diff_contracts,
        load_contract,
        migration_safety_checks,
    )

    try:
        old_contract = load_contract(args.old)
        new_contract = load_contract(args.new)
    except ValueError as exc:
        return _render_output(
            {
                "ok": False,
                "error_code": ERROR_CODES["unexpected"],
                "message": str(exc),
            },
            args.json,
        )

    diffs = diff_contracts(old_contract, new_contract)
    issues = migration_safety_checks(diffs)

    if args.json:
        return _render_output(
            {
                "ok": len(issues) == 0,
                "error_code": None,
                "message": (
                    f"{len(issues)} migration risk(s) found."
                    if issues else "No migration risks detected."
                ),
                "details": issues,
            },
            args.json,
        )

    if not issues:
        print("No migration risks detected — contracts are safe.")
        return 0

    danger = [i for i in issues if i["severity"] == "DANGER"]
    warning = [i for i in issues if i["severity"] == "WARNING"]

    if danger:
        print(f"=== DANGER ({len(danger)}) ===")
        for i in danger:
            loc = f"{i['model']}.{i['field']}" if i["field"] else i["model"]
            print(f"  {loc}: {i['message']}")
    if warning:
        print(f"=== WARNING ({len(warning)}) ===")
        for i in warning:
            loc = f"{i['model']}.{i['field']}" if i["field"] else i["model"]
            print(f"  {loc}: {i['message']}")

    print(f"\n{len(issues)} total migration risk(s) found.")
    return 0 if not danger else 1
```

Add the `safety` subcommand in `build_parser()` after the `diff` subcommand:

```python
    safety_cmd = contract_sub.add_parser(
        "safety", help="Check contract changes for migration safety risks"
    )
    safety_cmd.add_argument("--old", required=True, help="Path to older contract YAML")
    safety_cmd.add_argument("--new", required=True, help="Path to newer contract YAML")
    safety_cmd.set_defaults(func=_contract_safety)
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest workbook/tests/test_migration_safety.py -x --tb=short`
Expected: 10 passed

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest --tb=short -q`
Expected: 242 passed

- [ ] **Step 5: Commit**

```bash
git add deployment/wb_cli.py workbook/tests/test_migration_safety.py
git commit -m "feat: wb contract safety CLI subcommand"
```

---

### Task 4: Manual smoke test

- [ ] **Step 1: Create contracts and run safety check**

```bash
cat > /tmp/old.yaml << 'EOF'
version: "1.1"
source: {provider: google_sheets}
tables:
  - suggested_model_name: crop
    columns:
      - suggested_field_name: name
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 200, null: true}
      - suggested_field_name: legacy_id
        django_field_class: models.IntegerField
        django_field_kwargs: {}
    model_meta:
      verbose_name: Crop
      unique_together: [["name"]]
EOF

cat > /tmp/new.yaml << 'EOF'
version: "1.1"
source: {provider: google_sheets}
tables:
  - suggested_model_name: crop
    columns:
      - suggested_field_name: name
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 100, unique: true}
      - suggested_field_name: variety
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 100}
    model_meta:
      verbose_name: Crop
      unique_together: [["name", "variety"]]
EOF

python -m deployment.wb_cli contract safety --old /tmp/old.yaml --new /tmp/new.yaml
```

Expected output shows DANGER (nullable→non-nullable, field removed) and WARNING (max_length decreased, unique added, non-nullable field added) items.

- [ ] **Step 2: Test JSON output**

```bash
python -m deployment.wb_cli contract safety --old /tmp/old.yaml --new /tmp/new.yaml --json | python -m json.tool
```

Expected: valid JSON with `details` list.

- [ ] **Step 3: Test identical contracts produce safe result**

```bash
python -m deployment.wb_cli contract safety --old /tmp/old.yaml --new /tmp/old.yaml
```

Expected: "No migration risks detected — contracts are safe."
