# 0.7.x Issue Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship targeted hardening fixes for issues #4–#13 (contract composition, review suppression, safer scaffolding/codegen, and minor CLI/docs updates) on the `0.7.x-issues` branch.

**Architecture:** Keep the contract as the source of truth; implement `!include_list` + `tables` flattening in the contract loader; enforce per-table review suppression via stable rule IDs; remove generator backup side-effects; adjust `wb` CLI behavior only where required (`--exit-zero`).

**Tech Stack:** Python 3.12, Django management commands, PyYAML contract parsing, pytest + pytest-django, `wb` CLI (`deployment/wb_cli.py`).

---

## File Map (Planned Changes)

**Core implementation:**

- Modify: `workbook/codegen/contract.py`
  - Add `!include_list` YAML tag support
  - Flatten nested lists in `contract["tables"]`
  - Preserve `extra_fields` ordering in `get_fields()`
  - Validate FK targets using resolved fields (includes `extra_fields`)
  - Add `suppress_review_warnings` support in `review_contract()`

- Modify: `workbook/codegen/python_render.py`
  - Normalize `choices: EnumName.choices` to render as `choices=EnumName.choices` when the enum exists

- Modify: `workbook/management/commands/generate_models.py`
  - Remove `.bak` backup behavior on `--force`

- Modify: `workbook/management/commands/generate_admin.py`
  - Remove `.bak` backup behavior on `--force`

- Modify: `deployment/wb_cli.py`
  - Add `wb contract review --exit-zero`

- Modify: `scripts/new_product.py`
  - Prevent auto-commit when scaffolding into an existing git repo
  - Update scaffolded product Makefile: `corpus-codegen-report` uses `--exit-zero`; `generate-admin` works without a manifest

**Docs/Make:**

- Modify: `Makefile` (repo root)
  - Update `diff-generated` target (stop referencing `.bak`)

- Modify: `docs/roadmap.md`
  - Remove `.bak`-based diff guidance; reference `--diff` and git

- Modify: `workbook/README.md`
  - Document `choices` contract rule (bare enum name)

**Tests:**

- Create: `workbook/tests/test_contract_includes.py` (new)
- Modify: `workbook/tests/test_model_generator.py` (add ordering + choices tests)
- Create: `workbook/tests/test_contract_validation.py` (new)
- Modify: `workbook/tests/test_contract_review.py` (add suppression test)
- Create: `workbook/tests/test_codegen_force_overwrite.py` (new)
- Create: `deployment/tests/test_wb_contract_review_exit_zero.py` (new)
- Modify: `scripts/tests/test_new_product.py` (assert scaffold Makefile content)
- Modify: `examples/tests/test_new_product_scaffold.py` (add existing-repo no-auto-commit test)

---

## Task 1: Implement `!include_list` and `tables` Flattening

**Files:**

- Create: `workbook/tests/test_contract_includes.py`
- Modify: `workbook/codegen/contract.py`

- [ ] **Step 1: Write failing tests for `!include_list` and flattening**

Create `workbook/tests/test_contract_includes.py`:

```python
"""Tests for schema-contract YAML include tags and table list composition."""

from __future__ import annotations

from pathlib import Path

import pytest

from workbook.codegen.contract import load_contract


def test_include_list_splices_into_tables(tmp_path: Path) -> None:
    contract_path = tmp_path / "contract.yaml"
    included_tables_path = tmp_path / "profiled-tables.yaml"

    included_tables_path.write_text(
        """
- suggested_model_name: crop
  columns: []
- suggested_model_name: planting
  columns: []
""".lstrip(),
        encoding="utf-8",
    )

    contract_path.write_text(
        """
version: "1.3"
source: {}
tables:
  - suggested_model_name: field_event
    source_tab: null
    columns: []
    extra_fields: {}
  - !include_list profiled-tables.yaml
""".lstrip(),
        encoding="utf-8",
    )

    contract = load_contract(contract_path)
    model_names = [t.get("suggested_model_name") for t in contract["tables"]]
    assert model_names == ["field_event", "crop", "planting"]


def test_include_list_requires_a_yaml_list(tmp_path: Path) -> None:
    contract_path = tmp_path / "contract.yaml"
    included_path = tmp_path / "not-a-list.yaml"

    included_path.write_text(
        """
version: "1.3"
tables: []
""".lstrip(),
        encoding="utf-8",
    )

    contract_path.write_text(
        """
version: "1.3"
tables:
  - !include_list not-a-list.yaml
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"include_list expects a YAML list"):
        load_contract(contract_path)


def test_tables_flattening_is_recursive(tmp_path: Path) -> None:
    """Nested lists from chained includes should splice fully."""
    contract_path = tmp_path / "contract.yaml"
    first_list_path = tmp_path / "first.yaml"
    second_list_path = tmp_path / "second.yaml"

    second_list_path.write_text(
        """
- suggested_model_name: c
  columns: []
""".lstrip(),
        encoding="utf-8",
    )
    first_list_path.write_text(
        """
- suggested_model_name: a
  columns: []
- !include_list second.yaml
- suggested_model_name: b
  columns: []
""".lstrip(),
        encoding="utf-8",
    )
    contract_path.write_text(
        """
version: "1.3"
tables:
  - !include_list first.yaml
""".lstrip(),
        encoding="utf-8",
    )

    contract = load_contract(contract_path)
    model_names = [t.get("suggested_model_name") for t in contract["tables"]]
    assert model_names == ["a", "c", "b"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest workbook/tests/test_contract_includes.py -v`

Expected: FAIL (unknown YAML tag `!include_list`, and/or tables not flattened).

- [ ] **Step 3: Implement `!include_list` and flattening in loader**

Modify `workbook/codegen/contract.py`:

1. Register a second YAML constructor `!include_list` alongside `!include`.
1. Ensure it loads the referenced file relative to the including contract.
1. Enforce the included value is a list.
1. After YAML load, flatten `raw["tables"]` recursively (splice nested lists).

Add/replace these blocks inside `_make_contract_loader()`:

```python
    def _include_list_constructor(
        loader: ContractLoader, node: yaml.ScalarNode
    ) -> Any:
        path_str: str = str(loader.construct_scalar(node))
        target = (base_dir / path_str).resolve()
        if target in loader._include_stack:
            cycle = " -> ".join(str(p) for p in loader._include_stack + [target])
            raise ValueError(f"cyclic include detected: {cycle}")
        if not target.is_file():
            raise ValueError(f"include file not found: {target}")
        loader._include_stack.append(target)
        try:
            text = target.read_text(encoding="utf-8")
            loaded = yaml.load(text, Loader=type(loader))
        finally:
            loader._include_stack.pop()

        if not isinstance(loaded, list):
            raise ValueError(
                f"include_list expects a YAML list; got {type(loaded).__name__}: {target}"
            )
        return loaded

    ContractLoader.add_constructor("!include", _include_constructor)
    ContractLoader.add_constructor("!include_list", _include_list_constructor)
```

Then, inside `load_contract()` after `raw.setdefault("tables", [])`, normalize `tables`:

```python
    tables_raw = raw.get("tables")
    if tables_raw is None:
        tables_raw = []
    if not isinstance(tables_raw, list):
        raise ValueError("schema contract tables must be a YAML sequence")

    flattened_tables: list[Any] = []

    def _flatten_table_entries(table_entry: Any) -> None:
        if isinstance(table_entry, list):
            for nested_entry in table_entry:
                _flatten_table_entries(nested_entry)
            return
        flattened_tables.append(table_entry)

    for entry in tables_raw:
        _flatten_table_entries(entry)

    for table_entry in flattened_tables:
        if not isinstance(table_entry, dict):
            raise ValueError(
                "schema contract tables must be a list of mappings after includes"
            )
    raw["tables"] = flattened_tables
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest workbook/tests/test_contract_includes.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add workbook/codegen/contract.py workbook/tests/test_contract_includes.py
git commit -m "feat(workbook): add !include_list and splice tables"
```

---

## Task 2: Preserve `extra_fields` Declaration Order

**Files:**

- Modify: `workbook/codegen/contract.py`
- Modify: `workbook/tests/test_model_generator.py`

- [ ] **Step 1: Add failing test for `extra_fields` order**

Append to `workbook/tests/test_model_generator.py` near the `get_fields` section:

```python

def test_get_fields_preserves_extra_fields_order():
    table = {
        "suggested_model_name": "planting",
        "columns": [],
        "extra_fields": {
            "block": {
                "class": "models.ForeignKey",
                "kwargs": {"to": "FieldBlock", "on_delete": "models.PROTECT"},
            },
            "notes": {
                "class": "models.TextField",
                "kwargs": {"blank": True, "default": ""},
            },
        },
    }
    fields = get_fields(table)
    assert [f["name"] for f in fields] == ["block", "notes"]
```

- [ ] **Step 2: Run the test to verify failure**

Run: `pytest workbook/tests/test_model_generator.py::test_get_fields_preserves_extra_fields_order -v`

Expected: FAIL (current code sorts `extra_fields`).

- [ ] **Step 3: Implement order preservation**

Modify `workbook/codegen/contract.py` `get_fields()` to iterate `extra_fields` in insertion order:

Replace:

```python
    for fname, spec in sorted(extra.items()):
```

With:

```python
    for fname, spec in extra.items():
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest workbook/tests/test_model_generator.py::test_get_fields_preserves_extra_fields_order -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add workbook/codegen/contract.py workbook/tests/test_model_generator.py
git commit -m "fix(workbook): preserve extra_fields order in get_fields"
```

---

## Task 3: Validate FK Targets for `extra_fields`

**Files:**

- Create: `workbook/tests/test_contract_validation.py`
- Modify: `workbook/codegen/contract.py`

- [ ] **Step 1: Write failing test covering FK validation in `extra_fields`**

Create `workbook/tests/test_contract_validation.py`:

```python
"""Tests for validate_contract_tables warnings."""

from __future__ import annotations

from workbook.codegen.contract import validate_contract_tables


def test_validate_contract_tables_checks_fk_targets_in_extra_fields() -> None:
    contract = {
        "version": "1.3",
        "tables": [
            {
                "suggested_model_name": "event",
                "columns": [],
                "extra_fields": {
                    "crop": {
                        "class": "models.ForeignKey",
                        "kwargs": {"to": "Crop", "on_delete": "models.PROTECT"},
                    }
                },
                "str_template": "{self.pk}",
            }
        ],
    }
    warnings = validate_contract_tables(contract)
    assert any("Event.crop" in w and "Crop" in w for w in warnings)
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest workbook/tests/test_contract_validation.py -v`

Expected: FAIL (extra_fields FK targets not checked).

- [ ] **Step 3: Update `validate_contract_tables` to check resolved FK fields**

Modify `workbook/codegen/contract.py` `validate_contract_tables()`:

Replace the existing `for col in table.get("columns") ...` FK loop with a loop over resolved fields:

```python
        for field in get_fields(table):
            if field["class"] != "models.ForeignKey":
                continue
            fk_to = (field.get("kwargs") or {}).get("to")
            if fk_to and fk_to not in table_names and fk_to != "self":
                warnings.append(
                    f"{name}.{field['name']}: FK target \"{fk_to}\" "
                    f"is not a table in the contract"
                )
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest workbook/tests/test_contract_validation.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add workbook/codegen/contract.py workbook/tests/test_contract_validation.py
git commit -m "fix(workbook): validate FK targets for extra_fields"
```

---

## Task 4: Add `suppress_review_warnings` with Rule IDs

**Files:**

- Modify: `workbook/codegen/contract.py`
- Modify: `workbook/tests/test_contract_review.py`

- [ ] **Step 1: Add failing test for suppression of `multiple_fk_without_unique`**

Append to `workbook/tests/test_contract_review.py`:

```python

    def test_suppress_review_warning_multiple_fk_without_unique(self):
        contract = {
            "version": "1.3",
            "tables": [
                {
                    "suggested_model_name": "field_event",
                    "columns": [
                        {
                            "source_column": "Crop",
                            "suggested_field_name": "crop",
                            "django_field_class": "models.ForeignKey",
                            "django_field_kwargs": {"to": "Crop", "on_delete": "models.PROTECT"},
                        },
                        {
                            "source_column": "Block",
                            "suggested_field_name": "block",
                            "django_field_class": "models.ForeignKey",
                            "django_field_kwargs": {"to": "FieldBlock", "on_delete": "models.PROTECT"},
                        },
                    ],
                    "suppress_review_warnings": ["multiple_fk_without_unique"],
                    "str_template": "{self.pk}",
                },
                {
                    "suggested_model_name": "crop",
                    "columns": [],
                    "str_template": "{self.pk}",
                },
                {
                    "suggested_model_name": "field_block",
                    "columns": [],
                    "str_template": "{self.pk}",
                },
            ],
        }
        issues = review_contract(contract)
        assert not any("multiple FK fields" in i["message"] for i in issues)
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest workbook/tests/test_contract_review.py::TestReviewContract::test_suppress_review_warning_multiple_fk_without_unique -v`

Expected: FAIL (suppression not implemented).

- [ ] **Step 3: Implement rule IDs and suppression filter**

Modify `workbook/codegen/contract.py`:

1. Add stable `rule_id` values to every issue dict.
1. Read `table.get("suppress_review_warnings")` as a list of strings.
1. Skip appending issues whose `rule_id` is suppressed for that table.

Add helper near `review_contract`:

```python
def _suppressed_review_rule_ids(table: dict[str, Any]) -> set[str]:
    raw = table.get("suppress_review_warnings")
    if raw and isinstance(raw, list):
        return {str(rule_id) for rule_id in raw}
    return set()


def _append_review_issue(
    issues: list[dict[str, str]],
    *,
    table: dict[str, Any],
    table_name: str,
    field_name: str,
    message: str,
    rule_id: str,
) -> None:
    if rule_id in _suppressed_review_rule_ids(table):
        return
    issues.append(
        {
            "table": table_name,
            "field": field_name,
            "message": message,
            "rule_id": rule_id,
        }
    )
```

Then replace direct `issues.append({ ... })` calls in `review_contract()` with `_append_review_issue(...)`. For the multiple-FK warning, use `rule_id="multiple_fk_without_unique"`.

- [ ] **Step 4: Run targeted test to verify pass**

Run: `pytest workbook/tests/test_contract_review.py::TestReviewContract::test_suppress_review_warning_multiple_fk_without_unique -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add workbook/codegen/contract.py workbook/tests/test_contract_review.py
git commit -m "feat(workbook): allow per-table suppression of review warnings"
```

---

## Task 5: Add `wb contract review --exit-zero`

**Files:**

- Modify: `deployment/wb_cli.py`
- Create: `deployment/tests/test_wb_contract_review_exit_zero.py`

- [ ] **Step 1: Write failing tests for exit-zero behavior**

Create `deployment/tests/test_wb_contract_review_exit_zero.py`:

```python
"""Tests for `wb contract review --exit-zero`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from deployment.wb_cli import _contract_review


def _write_contract_with_review_issues(contract_path: Path) -> None:
    contract_path.write_text(
        """
version: "1.3"
tables:
  - suggested_model_name: crop
    columns:
      - source_column: Name
        suggested_field_name: name
        django_field_class: models.CharField
        django_field_kwargs: {}
""".lstrip(),
        encoding="utf-8",
    )


def test_contract_review_exit_zero_returns_0(tmp_path: Path) -> None:
    contract_path = tmp_path / "contract.yaml"
    _write_contract_with_review_issues(contract_path)

    args = argparse.Namespace(contract=str(contract_path), json=False, exit_zero=True)
    rc = _contract_review(args)
    assert rc == 0


def test_contract_review_default_returns_1(tmp_path: Path) -> None:
    contract_path = tmp_path / "contract.yaml"
    _write_contract_with_review_issues(contract_path)

    args = argparse.Namespace(contract=str(contract_path), json=False, exit_zero=False)
    rc = _contract_review(args)
    assert rc == 1


def test_contract_review_exit_zero_json_marks_ok_true(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.yaml"
    _write_contract_with_review_issues(contract_path)

    args = argparse.Namespace(contract=str(contract_path), json=True, exit_zero=True)
    rc = _contract_review(args)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert "issue" in payload["message"].lower()
    assert payload.get("details")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest deployment/tests/test_wb_contract_review_exit_zero.py -v`

Expected: FAIL (arg not supported / behavior unchanged).

- [ ] **Step 3: Implement `--exit-zero` in `wb` CLI**

Modify `deployment/wb_cli.py`:

1. In `build_parser()`, add the flag to the review subparser:

```python
    review_cmd.add_argument(
        "--exit-zero",
        action="store_true",
        help="Exit 0 even when issues are found (report-only mode).",
    )
```

2. In `_contract_review(args)`, when issues exist:

- For `args.json == True` and `args.exit_zero == True`: return a payload with `ok=True` and include `details` containing issues.
- For `args.json == False` and `args.exit_zero == True`: print issues as today, but return `0`.

Implement the issue branch like this:

```python
    issues = review_contract(contract)
    if not issues:
        return _render_output(
            {
                "ok": True,
                "error_code": None,
                "message": f"No issues found in {args.contract}.",
            },
            args.json,
        )

    if args.json:
        return _render_output(
            {
                "ok": bool(args.exit_zero),
                "error_code": None,
                "message": (
                    f"{len(issues)} issue(s) found (exit-zero)."
                    if args.exit_zero
                    else f"{len(issues)} issue(s) found."
                ),
                "details": issues,
            },
            args.json,
        )

    print(f"Found {len(issues)} issue(s) in {args.contract}:")
    for issue in issues:
        location = (
            f"{issue['table']}.{issue['field']}" if issue["field"] else issue["table"]
        )
        print(f"  - {location}: {issue['message']}")
    return 0 if args.exit_zero else 1
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest deployment/tests/test_wb_contract_review_exit_zero.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add deployment/wb_cli.py deployment/tests/test_wb_contract_review_exit_zero.py
git commit -m "feat(deployment): add wb contract review --exit-zero"
```

---

## Task 6: Update Scaffolded Product Makefile Targets

**Files:**

- Modify: `scripts/new_product.py`
- Modify: `scripts/tests/test_new_product.py`

- [ ] **Step 1: Add failing tests asserting updated Makefile content**

Extend `scripts/tests/test_new_product.py`:

```python

def test_corpus_codegen_report_is_report_only():
    """corpus-codegen-report should not fail the build on review warnings."""
    content = render_makefile()
    assert "wb contract review --contract \"$(CONTRACT)\" --exit-zero" in content


def test_generate_admin_does_not_require_manifest_file():
    """generate-admin should run even when view-manifest.yaml is absent."""
    content = render_makefile()
    assert "View manifest not found" not in content
    assert "--manifest \"$(VIEW_MANIFEST)\"" in content
    assert "if [ -f \"$(VIEW_MANIFEST)\" ]" in content
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest scripts/tests/test_new_product.py -v`

Expected: FAIL.

- [ ] **Step 3: Update Makefile template in `render_makefile()`**

Modify `scripts/new_product.py` `render_makefile()`:

1. In `corpus-codegen-report`, update the review line:

```make
wb contract review --contract "$(CONTRACT)" --exit-zero
```

2. In `generate-admin`, replace the hard `test -f` guard with a conditional invocation:

```make
generate-admin:
	@if [ -f "$(VIEW_MANIFEST)" ]; then \
		$(MANAGE) generate_admin --contract "$(CONTRACT)" --manifest "$(VIEW_MANIFEST)" --out "$(CORE)/admin.py" --app-label core --force; \
	else \
		$(MANAGE) generate_admin --contract "$(CONTRACT)" --out "$(CORE)/admin.py" --app-label core --force; \
	fi
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest scripts/tests/test_new_product.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/new_product.py scripts/tests/test_new_product.py
git commit -m "fix(scripts): make scaffold codegen targets less brittle"
```

---

## Task 7: Remove `.bak` Backups From Codegen Commands

**Files:**

- Modify: `workbook/management/commands/generate_models.py`
- Modify: `workbook/management/commands/generate_admin.py`
- Create: `workbook/tests/test_codegen_force_overwrite.py`
- Modify: `Makefile`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Write failing tests asserting no `.bak` is produced**

Create `workbook/tests/test_codegen_force_overwrite.py`:

```python
"""Tests for codegen overwrite behavior (no .bak side effects)."""

from __future__ import annotations

from pathlib import Path

import yaml
from django.core.management import call_command


def _write_minimal_contract(contract_path: Path) -> None:
    contract = {
        "version": "1.3",
        "tables": [
            {
                "suggested_model_name": "crop",
                "columns": [
                    {
                        "source_column": "Name",
                        "suggested_field_name": "name",
                        "django_field_class": "models.CharField",
                        "django_field_kwargs": {"max_length": 100},
                    }
                ],
                "str_template": "{self.name}",
            }
        ],
    }
    contract_path.write_text(
        yaml.safe_dump(contract, sort_keys=False),
        encoding="utf-8",
    )


def test_generate_models_force_does_not_create_backup(tmp_path: Path) -> None:
    contract_path = tmp_path / "contract.yaml"
    _write_minimal_contract(contract_path)

    out_path = tmp_path / "models.py"
    out_path.write_text("# old\n", encoding="utf-8")

    call_command(
        "generate_models",
        contract=str(contract_path),
        out=str(out_path),
        app_label="core",
        force=True,
    )

    assert out_path.exists()
    assert not (tmp_path / "models.py.bak").exists()


def test_generate_admin_force_does_not_create_backup(tmp_path: Path) -> None:
    contract_path = tmp_path / "contract.yaml"
    _write_minimal_contract(contract_path)

    out_path = tmp_path / "admin.py"
    out_path.write_text("# old\n", encoding="utf-8")

    call_command(
        "generate_admin",
        contract=str(contract_path),
        out=str(out_path),
        app_label="core",
        force=True,
    )

    assert out_path.exists()
    assert not (tmp_path / "admin.py.bak").exists()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest workbook/tests/test_codegen_force_overwrite.py -v`

Expected: FAIL (current commands create `.bak`).

- [ ] **Step 3: Remove `.bak` behavior in `generate_models`**

Modify `workbook/management/commands/generate_models.py`:

Replace:

```python
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists() and str(out_path) != "/dev/null":
            out_path.rename(str(out_path) + ".bak")
        out_path.write_text(source, encoding="utf-8")
```

With:

```python
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(source, encoding="utf-8")
```

- [ ] **Step 4: Remove `.bak` behavior in `generate_admin`**

Modify `workbook/management/commands/generate_admin.py`:

Remove the `out_path.rename(str(out_path) + ".bak")` block. Keep the diff printing (it is still useful), but do not create a backup file.

- [ ] **Step 5: Update repo root `diff-generated` target**

Modify `Makefile`:

Replace the `.bak`-based diff with `--diff`:

```make
diff-generated:
	$(MANAGE) generate_models --contract "$(CONTRACT)" --out "$(OUT)" --diff
```

- [ ] **Step 6: Update docs referencing `.bak`**

Modify `docs/roadmap.md` to remove guidance like `diff -u models.py.bak models.py` and instead reference:

1. `python manage.py generate_models --contract ... --out ... --diff`
1. `git diff` for tracked outputs

- [ ] **Step 7: Run tests to verify pass**

Run: `pytest workbook/tests/test_codegen_force_overwrite.py -v`

Expected: PASS.

- [ ] **Step 8: Run full gate**

Run: `make chassis-gate`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add \
  workbook/management/commands/generate_models.py \
  workbook/management/commands/generate_admin.py \
  workbook/tests/test_codegen_force_overwrite.py \
  Makefile \
  docs/roadmap.md
git commit -m "fix(workbook): stop writing .bak backups on --force"
```

---

## Task 8: Accept `choices: EnumName.choices` and Document Format

**Files:**

- Modify: `workbook/codegen/python_render.py`
- Modify: `workbook/tests/test_model_generator.py`
- Modify: `workbook/README.md`

- [ ] **Step 1: Add failing tests for `choices` normalization**

Append to `workbook/tests/test_model_generator.py` in the `render_field_kwargs` section:

```python

def test_render_field_kwargs_choices_accepts_bare_enum_name():
    result = render_field_kwargs({"choices": "EventType"}, enum_names={"EventType"})
    assert result == "choices=EventType.choices"


def test_render_field_kwargs_choices_accepts_enum_dot_choices():
    result = render_field_kwargs(
        {"choices": "EventType.choices"},
        enum_names={"EventType"},
    )
    assert result == "choices=EventType.choices"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest workbook/tests/test_model_generator.py::test_render_field_kwargs_choices_accepts_enum_dot_choices -v`

Expected: FAIL (currently rendered as a quoted string).

- [ ] **Step 3: Implement normalization in `render_field_kwargs`**

Modify `workbook/codegen/python_render.py` `render_field_kwargs()` by replacing the existing `choices` branch with:

```python
        elif k == "choices" and enum_names and isinstance(v, str):
            enum_name = v.removesuffix(".choices") if v.endswith(".choices") else v
            if enum_name in enum_names:
                parts.append(f"choices={enum_name}.choices")
            else:
                parts.append(f"{k}={v!r}")
```

- [ ] **Step 4: Update docs explaining contract `choices` format**

In `workbook/README.md`, add a short note near the contract examples:

```yaml
kwargs:
  # Contract format: use the bare enum class name.
  # Codegen renders `choices=EventType.choices`.
  choices: EventType
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest workbook/tests/test_model_generator.py::test_render_field_kwargs_choices_accepts_enum_dot_choices -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add workbook/codegen/python_render.py workbook/tests/test_model_generator.py workbook/README.md
git commit -m "fix(workbook): normalize contract choices enum references"
```

---

## Task 9: Prevent Silent Auto-Commit When Scaffolding Into Existing Git Repos

**Files:**

- Modify: `scripts/new_product.py`
- Modify: `examples/tests/test_new_product_scaffold.py`

- [ ] **Step 1: Add failing end-to-end test for existing-repo scaffolds**

Append to `examples/tests/test_new_product_scaffold.py`:

```python

def test_new_product_does_not_commit_into_existing_repo(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "new_product.py"

    output_dir = tmp_path / "existing-repo"
    output_dir.mkdir(parents=True)

    subprocess.run(["git", "-C", str(output_dir), "init", "-b", "main"], check=True)
    (output_dir / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(output_dir), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(output_dir),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "baseline",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        [
            sys.executable,
            str(script_path),
            "river-farm",
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    log = subprocess.run(
        ["git", "-C", str(output_dir), "log", "--oneline", "-1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "baseline" in log
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest examples/tests/test_new_product_scaffold.py::test_new_product_does_not_commit_into_existing_repo -v`

Expected: FAIL (script creates an unexpected commit).

- [ ] **Step 3: Fix `_git_init_and_initial_commit` to only commit after `git init`**

Modify `scripts/new_product.py` `_git_init_and_initial_commit(repo)`:

1. If `has_git` is true (repo already initialized), return immediately without `git add` or `git commit`.
1. Only run `git add -A` and `git commit ...` when this function successfully ran `git init`.

- [ ] **Step 4: Run test to verify pass**

Run: `pytest examples/tests/test_new_product_scaffold.py::test_new_product_does_not_commit_into_existing_repo -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/new_product.py examples/tests/test_new_product_scaffold.py
git commit -m "fix(scripts): avoid auto-commit in existing repos"
```

---

## Task 10: Full Regression Run

**Files:** none (verification)

- [ ] **Step 1: Run full gate**

Run: `make chassis-gate`

Expected: PASS.
