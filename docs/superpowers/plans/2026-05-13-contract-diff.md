# Contract Diff Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `diff_contracts()` function and `wb contract diff` CLI to compare two schema-contract YAML files and emit structured deltas.

**Architecture:** Single `diff_contracts(old, new)` function in `contract.py` returns a dict of model/field/meta diffs. CLI handler in `wb_cli.py` renders text/JSON output. TDD throughout.

**Tech Stack:** Python 3.12+, `argparse` for CLI, no new dependencies.

---

### Task 1: Write tests for `diff_contracts()`

**Files:**
- Create: `workbook/tests/test_contract_diff.py` (new file)
- Modify: (none)

- [ ] **Step 1: Write `test_diff_identical_returns_no_changes`**

```python
"""Tests for workbook.codegen.contract.diff_contracts."""

from __future__ import annotations

from workbook.codegen.contract import diff_contracts


def _make_table(name, fields=None, meta=None):
    """Build a minimal contract table dict."""
    table = {
        "suggested_model_name": name,
        "columns": fields or [],
    }
    if meta:
        table["model_meta"] = meta
    return table


def test_diff_identical_contracts():
    """Two identical contracts produce an empty diff."""
    contract = {
        "version": "1.1",
        "source": {"provider": "google_sheets"},
        "tables": [
            _make_table("crop", [
                {"suggested_field_name": "name",
                 "django_field_class": "models.CharField",
                 "django_field_kwargs": {"max_length": 200}},
            ]),
        ],
    }
    result = diff_contracts(contract, contract)
    assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest workbook/tests/test_contract_diff.py::test_diff_identical_contracts -x --tb=short`
Expected: FAIL with `ImportError: cannot import name 'diff_contracts'`

- [ ] **Step 3: Write test for model added/removed**

```python
def test_diff_model_added_and_removed():
    old_contract = {
        "version": "1.1",
        "source": {},
        "tables": [
            _make_table("crop"),
            _make_table("legacy_crop"),
        ],
    }
    new_contract = {
        "version": "1.1",
        "source": {},
        "tables": [
            _make_table("crop"),
            _make_table("inventory_entry"),
        ],
    }
    result = diff_contracts(old_contract, new_contract)
    assert "models_removed" in result
    assert "LegacyCrop" in result["models_removed"]
    assert "models_added" in result
    assert "InventoryEntry" in result["models_added"]
```

- [ ] **Step 4: Write test for field added/removed/changed**

```python
def test_diff_field_changes():
    old_table = _make_table("crop", [
        {"suggested_field_name": "name",
         "django_field_class": "models.CharField",
         "django_field_kwargs": {"max_length": 100}},
        {"suggested_field_name": "legacy_id",
         "django_field_class": "models.IntegerField",
         "django_field_kwargs": {}},
    ])
    new_table = _make_table("crop", [
        {"suggested_field_name": "name",
         "django_field_class": "models.CharField",
         "django_field_kwargs": {"max_length": 200}},
        {"suggested_field_name": "variety",
         "django_field_class": "models.CharField",
         "django_field_kwargs": {"max_length": 100}},
    ])
    old_contract = {"version": "1.1", "source": {}, "tables": [old_table]}
    new_contract = {"version": "1.1", "source": {}, "tables": [new_table]}
    result = diff_contracts(old_contract, new_contract)
    diffs = result["model_diffs"]["Crop"]
    assert diffs["fields_added"] == [
        {"name": "variety", "class": "models.CharField",
         "kwargs": {"max_length": 100}}
    ]
    assert diffs["fields_removed"] == [
        {"name": "legacy_id", "class": "models.IntegerField", "kwargs": {}}
    ]
    assert diffs["fields_changed"] == [
        {"name": "name",
         "class": {"old": "models.CharField", "new": "models.CharField"},
         "kwargs": {"max_length": {"old": 100, "new": 200}}}
    ]
```

- [ ] **Step 5: Write test for meta changes**

```python
def test_diff_meta_changes():
    old_table = _make_table("crop", meta={
        "verbose_name": "Crop",
        "unique_together": [["name"]],
        "ordering": ["name"],
    })
    new_table = _make_table("crop", meta={
        "verbose_name": "Crop",
        "unique_together": [["name", "variety"]],
        "ordering": ["name"],
    })
    old_contract = {"version": "1.1", "source": {}, "tables": [old_table]}
    new_contract = {"version": "1.1", "source": {}, "tables": [new_table]}
    result = diff_contracts(old_contract, new_contract)
    diffs = result["model_diffs"]["Crop"]
    assert "meta_changed" in diffs
    assert "unique_together" in diffs["meta_changed"]
    assert diffs["meta_changed"]["unique_together"] == {
        "old": [["name"]],
        "new": [["name", "variety"]],
    }
    # verbose_name and ordering unchanged — not in meta_changed
    assert "verbose_name" not in diffs["meta_changed"]
    assert "ordering" not in diffs["meta_changed"]
```

- [ ] **Step 6: Write test for field type (class) change**

```python
def test_diff_field_class_change():
    old_table = _make_table("crop", [
        {"suggested_field_name": "notes",
         "django_field_class": "models.TextField",
         "django_field_kwargs": {}},
    ])
    new_table = _make_table("crop", [
        {"suggested_field_name": "notes",
         "django_field_class": "models.CharField",
         "django_field_kwargs": {"max_length": 500}},
    ])
    old_contract = {"version": "1.1", "source": {}, "tables": [old_table]}
    new_contract = {"version": "1.1", "source": {}, "tables": [new_table]}
    result = diff_contracts(old_contract, new_contract)
    changed = result["model_diffs"]["Crop"]["fields_changed"]
    assert len(changed) == 1
    assert changed[0]["class"] == {
        "old": "models.TextField",
        "new": "models.CharField",
    }
    assert changed[0]["kwargs"]["max_length"] == {"old": None, "new": 500}
```

- [ ] **Step 7: Run all tests to verify they fail**

Run: `python -m pytest workbook/tests/test_contract_diff.py -x --tb=short`
Expected: 6 tests, all fail with `ImportError` or `NameError` for `diff_contracts`

---

### Task 2: Implement `diff_contracts()` in contract.py

**Files:**
- Modify: `workbook/codegen/contract.py` (add function at end, before module docstring close)

- [ ] **Step 1: Add `diff_contracts()` function**

Add to `workbook/codegen/contract.py` after line 583 (after `get_fields`):

```python
def diff_contracts(
    old: dict[str, Any],
    new: dict[str, Any],
) -> dict[str, Any]:
    """Compare two normalised schema contracts and return a structured diff.

    Compares tables (matched by ``suggested_model_name``), resolved fields
    per table, and ``model_meta`` options.  No fuzzy rename detection —
    models present in only one contract are reported as added/removed.

    Args:
        old: First (older) normalised contract dict.
        new: Second (newer) normalised contract dict.

    Returns:
        Dict keyed by diff category, or ``{}`` when contracts are identical.
        Shape documented in ``docs/superpowers/specs/2026-05-13-contract-diff-design.md``.
    """
    old_tables = {get_model_name(t): t for t in (old.get("tables") or [])}
    new_tables = {get_model_name(t): t for t in (new.get("tables") or [])}

    old_names = set(old_tables)
    new_names = set(new_tables)

    added_models = sorted(new_names - old_names)
    removed_models = sorted(old_names - new_names)
    common_models = sorted(old_names & new_names)

    if not added_models and not removed_models and not common_models:
        return {}

    result: dict[str, Any] = {}
    if added_models:
        result["models_added"] = added_models
    if removed_models:
        result["models_removed"] = removed_models

    model_diffs: dict[str, Any] = {}
    for name in common_models:
        diff = _diff_tables(old_tables[name], new_tables[name])
        if diff:
            model_diffs[name] = diff

    if model_diffs:
        result["model_diffs"] = model_diffs

    return result


def _diff_tables(
    old_table: dict[str, Any],
    new_table: dict[str, Any],
) -> dict[str, Any] | None:
    """Compare two tables with the same model name.

    Returns a diff dict or ``None`` when no differences are found.
    """
    old_fields = _field_map(get_fields(old_table))
    new_fields = _field_map(get_fields(new_table))

    old_names = set(old_fields)
    new_names = set(new_fields)

    result: dict[str, Any] = {}

    # Field additions / removals.
    added = sorted(new_names - old_names)
    if added:
        result["fields_added"] = [
            _field_summary(new_fields[f]) for f in added
        ]

    removed = sorted(old_names - new_names)
    if removed:
        result["fields_removed"] = [
            _field_summary(old_fields[f]) for f in removed
        ]

    # Field changes.
    changed: list[dict[str, Any]] = []
    for fname in sorted(old_names & new_names):
        of = old_fields[fname]
        nf = new_fields[fname]
        fc = _diff_fields(of, nf)
        if fc:
            changed.append(fc)
    if changed:
        result["fields_changed"] = changed

    # Meta changes.
    meta_diff = _diff_meta(
        old_table.get("model_meta") or {},
        new_table.get("model_meta") or {},
    )
    if meta_diff:
        result["meta_changed"] = meta_diff

    return result if result else None


def _field_map(fields: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index a field list by ``name``."""
    return {f["name"]: f for f in fields}


def _field_summary(field: dict[str, Any]) -> dict[str, Any]:
    """Return a clean, comparable field dict."""
    return {
        "name": field["name"],
        "class": field["class"],
        "kwargs": dict(field.get("kwargs") or {}),
    }


def _diff_fields(
    old: dict[str, Any],
    new: dict[str, Any],
) -> dict[str, Any] | None:
    """Compare two fields with the same name.

    Returns a change dict or ``None`` when fields are identical.
    """
    cls_old = old.get("class", "")
    cls_new = new.get("class", "")
    kwargs_old = dict(old.get("kwargs") or {})
    kwargs_new = dict(new.get("kwargs") or {})

    class_changed = cls_old != cls_new

    all_kwargs_keys = sorted(set(kwargs_old) | set(kwargs_new))
    kwarg_diffs: dict[str, dict[str, Any]] = {}
    for k in all_kwargs_keys:
        v_old = kwargs_old.get(k)
        v_new = kwargs_new.get(k)
        if v_old != v_new:
            kwarg_diffs[k] = {"old": v_old, "new": v_new}

    if not class_changed and not kwarg_diffs:
        return None

    entry: dict[str, Any] = {"name": old["name"]}

    if class_changed:
        entry["class"] = {"old": cls_old, "new": cls_new}

    if kwarg_diffs:
        entry["kwargs"] = kwarg_diffs

    return entry


def _diff_meta(
    old_meta: dict[str, Any],
    new_meta: dict[str, Any],
) -> dict[str, Any] | None:
    """Compare two ``model_meta`` dicts.

    Only keys present in ``DIFF_META_KEYS`` are compared.
    """
    DIFF_META_KEYS = {
        "unique_together", "indexes", "constraints",
        "ordering", "verbose_name", "db_table", "app_label",
    }
    result: dict[str, Any] = {}
    for key in DIFF_META_KEYS:
        v_old = old_meta.get(key)
        v_new = new_meta.get(key)
        if v_old != v_new:
            result[key] = {"old": v_old, "new": v_new}
    return result if result else None
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest workbook/tests/test_contract_diff.py -x --tb=short`
Expected: 6 passed

- [ ] **Step 3: Run full test suite to check nothing broke**

Run: `python -m pytest --tb=short -q`
Expected: 228 passed

- [ ] **Step 4: Commit**

```bash
git add workbook/codegen/contract.py workbook/tests/test_contract_diff.py
git commit -m "feat: contract diff engine — diff_contracts() function"
```

---

### Task 3: Add CLI subcommand

**Files:**
- Modify: `deployment/wb_cli.py` (add `_contract_diff()` handler + CLI wiring)

- [ ] **Step 1: Write test for `wb contract diff` CLI**

Add to `workbook/tests/test_contract_diff.py`:

```python
# CLI integration

def test_contract_diff_cli_text(tmp_path):
    """CLI emits human-readable text by default."""
    from deployment.wb_cli import main
    import sys

    old_path = tmp_path / "old.yaml"
    new_path = tmp_path / "new.yaml"
    old_path.write_text("version: '1.1'\nsource: {}\ntables: []\n")
    new_path.write_text("version: '1.1'\nsource: {}\ntables: []\n")

    sys.argv = ["wb", "contract", "diff",
                "--old", str(old_path),
                "--new", str(new_path)]
    rc = main()
    assert rc == 0


def test_contract_diff_cli_json(tmp_path, capsys):
    """CLI emits JSON with --json flag."""
    from deployment.wb_cli import main
    import sys
    import json

    old_path = tmp_path / "old.yaml"
    new_path = tmp_path / "new.yaml"
    old_path.write_text("version: '1.1'\nsource: {}\ntables: []\n")
    new_path.write_text("version: '1.1'\nsource: {}\ntables: []\n")

    sys.argv = ["wb", "contract", "diff",
                "--old", str(old_path),
                "--new", str(new_path),
                "--json"]
    rc = main()
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
```

- [ ] **Step 2: Add CLI handler + parser wiring**

In `deployment/wb_cli.py`, add `_contract_diff()` handler and register the subcommand in `build_parser()`.

```python
def _contract_diff(args: argparse.Namespace) -> int:
    _setup_django()
    from workbook.codegen.contract import diff_contracts, load_contract

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

    if not diffs:
        return _render_output(
            {
                "ok": True,
                "error_code": None,
                "message": "Contracts are identical.",
            },
            args.json,
        )

    if args.json:
        return _render_output(
            {
                "ok": True,
                "error_code": None,
                "message": "Differences found.",
                "diffs": diffs,
            },
            args.json,
        )

    # Human-readable text output
    lines: list[str] = []

    if diffs.get("models_added") or diffs.get("models_removed"):
        lines.append("=== Models ===")
        if diffs.get("models_added"):
            lines.append(f"  Added:   {', '.join(diffs['models_added'])}")
        if diffs.get("models_removed"):
            lines.append(f"  Removed: {', '.join(diffs['models_removed'])}")
        lines.append("")

    for model_name in sorted(diffs.get("model_diffs") or {}):
        md = diffs["model_diffs"][model_name]
        lines.append(f"=== Model: {model_name} ===")

        if md.get("fields_added"):
            lines.append("  Fields added:")
            for f in md["fields_added"]:
                kwargs_str = _fmt_kwargs(f.get("kwargs", {}))
                lines.append(f"    + {f['name']} ({_short_class(f['class'])}{kwargs_str})")

        if md.get("fields_removed"):
            lines.append("  Fields removed:")
            for f in md["fields_removed"]:
                kwargs_str = _fmt_kwargs(f.get("kwargs", {}))
                lines.append(f"    - {f['name']} ({_short_class(f['class'])}{kwargs_str})")

        if md.get("fields_changed"):
            lines.append("  Fields changed:")
            for fc in md["fields_changed"]:
                parts = [f"~ {fc['name']}"]
                if "class" in fc:
                    old_cls = _short_class(fc["class"]["old"])
                    new_cls = _short_class(fc["class"]["new"])
                    parts.append(f"{old_cls} -> {new_cls}")
                for kw, v in (fc.get("kwargs") or {}).items():
                    old_v = _fmt_value(v["old"])
                    new_v = _fmt_value(v["new"])
                    parts.append(f"{kw}: {old_v} -> {new_v}")
                lines.append("    " + ", ".join(parts))

        if md.get("meta_changed"):
            lines.append("  Meta changes:")
            for key, v in md["meta_changed"].items():
                old_v = _fmt_value(v["old"])
                new_v = _fmt_value(v["new"])
                lines.append(f"    ~ {key}: {old_v} -> {new_v}")

        lines.append("")

    print("\n".join(lines).rstrip())
    return 0


def _short_class(raw: str) -> str:
    return raw.removeprefix("models.")


def _fmt_kwargs(kwargs: dict) -> str:
    if not kwargs:
        return ""
    pairs = ", ".join(f"{k}={v!r}" for k, v in sorted(kwargs.items()))
    return f", {pairs}"


def _fmt_value(val: Any) -> str:
    if val is None:
        return "None"
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return str(val)
    if isinstance(val, dict):
        return str(val)
    return repr(val)
```

Add the `diff` subcommand after the `review` subcommand registration (around line 264):

```python
    diff_cmd = contract_sub.add_parser(
        "diff", help="Compare two schema contracts and show differences"
    )
    diff_cmd.add_argument("--old", required=True, help="Path to older contract YAML")
    diff_cmd.add_argument("--new", required=True, help="Path to newer contract YAML")
    diff_cmd.set_defaults(func=_contract_diff)
```

- [ ] **Step 3: Run tests to check CLI tests pass**

Run: `python -m pytest workbook/tests/test_contract_diff.py -x --tb=short`
Expected: 8 passed

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest --tb=short -q`
Expected: 230 passed

- [ ] **Step 5: Commit**

```bash
git add deployment/wb_cli.py workbook/tests/test_contract_diff.py
git commit -m "feat: wb contract diff CLI subcommand"
```

---

### Task 4: Manual smoke test

- [ ] **Step 1: Create two test contracts and run diff**

```bash
cat > /tmp/old.yaml << 'EOF'
version: "1.1"
source: {provider: google_sheets}
tables:
  - suggested_model_name: crop
    columns:
      - suggested_field_name: name
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 100}
      - suggested_field_name: legacy_id
        django_field_class: models.IntegerField
        django_field_kwargs: {}
    model_meta:
      verbose_name: Crop
      unique_together: [["name"]]
      ordering: ["name"]
  - suggested_model_name: legacy_crop
    columns:
      - suggested_field_name: name
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 100}
EOF

cat > /tmp/new.yaml << 'EOF'
version: "1.1"
source: {provider: google_sheets}
tables:
  - suggested_model_name: crop
    columns:
      - suggested_field_name: name
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 200}
      - suggested_field_name: variety
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 100}
    model_meta:
      verbose_name: Crop
      unique_together: [["name", "variety"]]
      ordering: ["name"]
  - suggested_model_name: inventory_entry
    columns:
      - suggested_field_name: product
        django_field_class: models.CharField
        django_field_kwargs: {max_length: 200}
EOF

python -m deployment.wb_cli contract diff --old /tmp/old.yaml --new /tmp/new.yaml
```

Expected output:
```
=== Models ===
  Added:   InventoryEntry
  Removed: LegacyCrop

=== Model: Crop ===
  Fields added:
    + variety (CharField, max_length=100)
  Fields removed:
    - legacy_id (IntegerField)
  Fields changed:
    ~ name, max_length: 100 -> 200
  Meta changes:
    ~ unique_together: [['name']] -> [['name', 'variety']]
```

- [ ] **Step 2: Test JSON output**

```bash
python -m deployment.wb_cli contract diff --old /tmp/old.yaml --new /tmp/new.yaml --json | python -m json.tool
```

Expected: valid JSON with diffs structure.
