# Pre-farm Launch Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the dedup bug, add autonomous Phase 0 commands, improve observability, and add dry-run mode ahead of the farm end-to-end test.

**Architecture:** Three new Django management commands bridge the agent from raw notes to Phase 1. The dedup bug is fixed by simplifying `domain_context.py` and moving tab-level logic into the deep-profiling loop in `cohort_corpus.py`. Makefile targets and scaffold templates are updated so instructions are executable.

**Tech Stack:** Python 3.11, Django management commands, pytest, ruff, make

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `profiler/tools/domain_context.py` | Modify | Simplify `deduplicate_index_records` to year-only filter |
| `profiler/tools/cohort_corpus.py` | Modify | Move dedup to deep loop, add `known_tabs` in full mode, normalize coverage bonus, fix glossary expansion |
| `profiler/management/commands/extract_workbook_codes.py` | Create | B1: read drive tree, extract codes, optionally update config |
| `profiler/management/commands/validate_domain_context.py` | Create | B2: validate YAML structure |
| `profiler/management/commands/draft_domain_context.py` | Create | B3: draft YAML from drive tree + raw notes |
| `profiler/management/commands/profile_cohort_corpus.py` | Modify | Add `--dry-run` flag |
| `workbook/makefile_targets.py` | Modify | Add `draft-domain-context`, `validate-domain-context`, `extract-workbook-codes`, `orient` targets |
| `scripts/new_product.py` | Modify | Update AGENTS.md Phase 0 template |
| `example_data/domain_context.example.yaml` | Modify | Add `_documentation` block and example exception |
| `example_data/drive_tree.example.json` | Create | Minimal synthetic tree for chassis gate |
| `Makefile` | Modify | Add chassis gate smoke tests |
| `profiler/tests/test_domain_context.py` | Modify | Update tests for simplified dedup |
| `profiler/tests/test_cohort_corpus_tools.py` | Modify | Add deep-loop dedup tests, coverage bonus test |
| `profiler/tests/test_extract_workbook_codes.py` | Create | Unit + CLI tests |
| `profiler/tests/test_validate_domain_context.py` | Create | Unit + CLI tests |
| `profiler/tests/test_draft_domain_context.py` | Create | Unit + CLI tests |

---

## Task 1: Simplify `deduplicate_index_records` (A1)

**Files:**
- Modify: `profiler/tools/domain_context.py:126-168`
- Test: `profiler/tests/test_domain_context.py:78-133`

- [ ] **Step 1: Rewrite `deduplicate_index_records` to filter archived years only**

```python
def deduplicate_index_records(
    index_records: list[dict],
    approved_tabs: dict[str, list[str]],
    domain_context: DomainContext | None,
) -> list[dict]:
    """Filter index records for Phase 3 deep profiling.

    Removes records for archived years. Tab-level deduplication
    (latest-year-per-tab and exceptions) is handled in the
    deep-profiling loop where tab_title is in scope.
    """
    if domain_context is None:
        return list(index_records)

    return [
        rec
        for rec in index_records
        if not domain_context.is_archived_year(rec.get("year"))
    ]
```

- [ ] **Step 2: Update tests in `test_domain_context.py`**

Replace the dedup tests (lines 78-133) with:

```python
def test_deduplicate_index_records_filters_archived():
    ctx = DomainContext(
        year_scope=DomainContext.YearScope(active=[2025, 2026], archived=[2023, 2024], forward=[]),
        deduplication=DomainContext.DeduplicationContext(strategy="latest_year", exceptions=[]),
    )
    records = [
        {"year": 2023, "workbook_code": "402", "spreadsheet_id": "s1"},
        {"year": 2025, "workbook_code": "402", "spreadsheet_id": "s3"},
        {"year": 2026, "workbook_code": "402", "spreadsheet_id": "s4"},
    ]
    approved = {"402": ["Crop Planner"]}
    filtered = deduplicate_index_records(records, approved, ctx)
    assert len(filtered) == 2
    assert {r["year"] for r in filtered} == {2025, 2026}


def test_deduplicate_index_records_no_domain_context():
    records = [{"year": 2023, "workbook_code": "402", "spreadsheet_id": "s1"}]
    approved = {"402": ["Crop Planner"]}
    filtered = deduplicate_index_records(records, approved, None)
    assert len(filtered) == 1
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest profiler/tests/test_domain_context.py -v
```
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add profiler/tools/domain_context.py profiler/tests/test_domain_context.py
git commit -m "fix: simplify deduplicate_index_records to year-only filter"
```

---

## Task 2: Move Tab-Level Dedup to Deep Loop (A1 continued)

**Files:**
- Modify: `profiler/tools/cohort_corpus.py:1505-1507` and surrounding loop
- Test: `profiler/tests/test_cohort_corpus_tools.py`

- [ ] **Step 1: Add pre-loop `latest_year_by_workbook` computation**

In `run_cohort_corpus`, before the deep-profiling loop (around line 1505), add:

```python
latest_year_by_workbook: dict[str, int] = {}
for rec in index_records:
    wb = rec["workbook_code"]
    yr = rec.get("year") or 0
    if yr > latest_year_by_workbook.get(wb, 0):
        latest_year_by_workbook[wb] = yr
```

- [ ] **Step 2: Modify the deep-profiling loop to apply tab-level dedup**

Replace the loop header at line 1509:

```python
for record in index_records:
    if _429_abort:
        break
    wb = record["workbook_code"]
    yr = record.get("year") or 0
    for tab_title in approved_tabs.get(wb, []):
        if known_tabs and (record["spreadsheet_id"], tab_title) not in known_tabs:
            continue
        if domain_context is not None:
            is_exception = domain_context.is_deduplication_exception(tab_title)
            if not is_exception and yr != latest_year_by_workbook.get(wb, 0):
                continue
        # existing deep profile logic continues unchanged
```

- [ ] **Step 3: Populate `known_tabs` in full mode (D3)**

In the full mode branch (after broad coverage is written, around line 1413), add:

```python
for inventory_row in broad_payload.get("inventory_rows", []):
    known_tabs.add((inventory_row["spreadsheet_id"], inventory_row["tab_title"]))
```

- [ ] **Step 4: Add dedup trace collection (D1)**

Before the deep loop, initialize:

```python
dedup_trace: dict[str, dict] = {}
```

Inside the loop, after the dedup `continue` checks, record:

```python
if domain_context is not None:
    trace_entry = dedup_trace.setdefault(wb, {
        "latest_year": latest_year_by_workbook.get(wb),
        "profiled_all_years": [],
        "profiled_latest_only": [],
    })
    is_exception = domain_context.is_deduplication_exception(tab_title)
    target_list = "profiled_all_years" if is_exception else "profiled_latest_only"
    if tab_title not in trace_entry[target_list]:
        trace_entry[target_list].append(tab_title)
```

Append `dedup_trace` to the deep coverage JSON payload (around line 1648):

```python
write_json(
    deep_coverage_path,
    {
        "job_count": len(deep_results),
        "success_count": sum(1 for row in deep_results if row["exit_code"] == 0),
        "failure_count": sum(1 for row in deep_results if row["exit_code"] != 0),
        "results": deep_results,
        "dedup_trace": dedup_trace,
    },
)
```

- [ ] **Step 5: Write test for deep-loop dedup**

Add to `profiler/tests/test_cohort_corpus_tools.py`:

```python
def test_run_cohort_corpus_deep_loop_dedup_skips_old_years(tmp_path: Path):
    corpus_out_dir = tmp_path / "corpus_run"
    corpus_out_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = "2026-05-20"

    workbook_index_payload = {
        "generated_from": f"drive_discovery_{date_stamp}.json",
        "record_count": 2,
        "records": [
            {"year": 2024, "workbook_code": "402", "spreadsheet_id": "s1", "spreadsheet_name": "402 2024"},
            {"year": 2026, "workbook_code": "402", "spreadsheet_id": "s2", "spreadsheet_name": "402 2026"},
        ],
    }
    index_path = corpus_out_dir / f"in_scope_workbook_index_{date_stamp}.json"
    index_path.write_text(json.dumps(workbook_index_payload), encoding="utf-8")

    broad_payload = {
        "run_count": 2,
        "success_count": 2,
        "failure_count": 0,
        "results": [],
        "inventory_rows": [
            {"spreadsheet_id": "s1", "sheet_id": 0, "rows": 100, "cols": 10, "tab_title": "Plan Board"},
            {"spreadsheet_id": "s2", "sheet_id": 0, "rows": 100, "cols": 10, "tab_title": "Plan Board"},
        ],
    }
    broad_path = corpus_out_dir / f"broad_profile_coverage_{date_stamp}.json"
    broad_path.write_text(json.dumps(broad_payload), encoding="utf-8")

    selection_path = corpus_out_dir / f"tab_selection_{date_stamp}.json"
    selection_path.write_text(
        json.dumps({"approved_tabs": {"402": ["Plan Board"]}}),
        encoding="utf-8",
    )

    from profiler.tools.domain_context import DomainContext
    corpus_config = {
        "folder_id": "drive-folder-1",
        "in_scope_workbooks": ["402"],
        "domain_context": None,
    }
    mock_drive = MagicMock()
    mock_sheets = MagicMock()

    with (
        patch("profiler.management.commands.profile_drive_folder.walk_folder") as mock_walk,
        patch("profiler.tools.cohort_corpus.list_tabs") as mock_list_tabs,
        patch("profiler.tools.cohort_corpus.fetch_tab_grid", return_value={"sheets": []}),
        patch("profiler.tools.cohort_corpus.summarize_tab", return_value={"formula_cell_count": 0}),
    ):
        outputs = run_cohort_corpus(
            drive_service=mock_drive,
            sheets_service=mock_sheets,
            config=corpus_config,
            out_dir=corpus_out_dir,
            date_stamp=date_stamp,
            resume_from_tab_selection=True,
        )

    mock_walk.assert_not_called()
    mock_list_tabs.assert_not_called()

    deep_coverage = json.loads(
        (corpus_out_dir / f"deep_profile_coverage_{date_stamp}.json").read_text(encoding="utf-8")
    )
    assert deep_coverage["success_count"] == 1
```

- [ ] **Step 6: Run tests**

```bash
.venv/bin/pytest profiler/tests/test_cohort_corpus_tools.py -v
```

- [ ] **Step 7: Commit**

```bash
git add profiler/tools/cohort_corpus.py profiler/tests/test_cohort_corpus_tools.py
git commit -m "fix: move tab-level dedup to deep loop, add dedup trace, populate known_tabs in full mode"
```

---

## Task 3: Normalize Coverage Bonus (D2)

**Files:**
- Modify: `profiler/tools/cohort_corpus.py:627`

- [ ] **Step 1: Change legacy coverage bonus threshold**

Replace line 627:

```python
# Old:
coverage_bonus = 1 if len(bucket["years"]) >= 3 else 0

# New:
coverage_bonus = 1 if len(bucket["years"]) >= 2 else 0
```

- [ ] **Step 2: Update test expectation**

In `profiler/tests/test_cohort_corpus_tools.py`, find `test_select_tabs_no_domain_context_unchanged` (around line 1661):

```python
# Old assertion:
assert entry["coverage_bonus"] == 1

# New assertion remains the same because the test uses 3 years,
# but add a new test for the 2-year threshold:

def test_select_tabs_legacy_coverage_bonus_two_years():
    index_records = [
        {"year": 2025, "workbook_code": "402", "spreadsheet_id": "s1", "spreadsheet_name": "402 2025"},
        {"year": 2026, "workbook_code": "402", "spreadsheet_id": "s2", "spreadsheet_name": "402 2026"},
    ]
    inventory_rows = [
        {"spreadsheet_id": "s1", "sheet_id": 1, "rows": 500, "cols": 20, "tab_title": "Crop Planner"},
        {"spreadsheet_id": "s2", "sheet_id": 1, "rows": 500, "cols": 20, "tab_title": "Crop Planner"},
    ]
    selected = select_tabs_from_inventory(
        index_records, inventory_rows,
        tab_score_heuristics={"operational_tokens": ["crop"]},
    )
    entry = next(r for r in selected if r["tab_title"] == "Crop Planner")
    assert entry["coverage_bonus"] == 1
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest profiler/tests/test_cohort_corpus_tools.py::test_select_tabs_legacy_coverage_bonus_two_years -v
```

- [ ] **Step 4: Commit**

```bash
git add profiler/tools/cohort_corpus.py profiler/tests/test_cohort_corpus_tools.py
git commit -m "fix: normalize legacy coverage bonus to >=2 years"
```

---

## Task 4: Fix Glossary Expansion Substring Safety (E1)

**Files:**
- Modify: `profiler/tools/cohort_corpus.py:408-455`

- [ ] **Step 1: Replace string concatenation with set-based matching in `score_tab`**

Replace lines 408-455:

```python
# Old:
lowered = title.lower()
if domain_context is not None and domain_context.glossary:
    title_expansions = glossary_expand(lowered, domain_context.glossary)
    if title_expansions:
        lowered = lowered + " " + " ".join(title_expansions)

# New:
match_texts = {title.lower()}
if domain_context is not None and domain_context.glossary:
    title_expansions = glossary_expand(title.lower(), domain_context.glossary)
    if title_expansions:
        match_texts.update(title_expansions)
```

Then in the token matching loop (around line 451), replace:

```python
# Old:
matched = [token for token in tokens if _token_match(token, lowered, match_mode)]

# New:
matched = []
for token in tokens:
    if any(_token_match(token, text, match_mode) for text in match_texts):
        matched.append(token)
```

Same change for the combo token check (around line 471):

```python
# Old:
if all(_token_match(token, lowered, match_mode) for token in combo):

# New:
if all(
    any(_token_match(token, text, match_mode) for text in match_texts)
    for token in combo
):
```

- [ ] **Step 2: Verify existing glossary test still passes**

```bash
.venv/bin/pytest profiler/tests/test_cohort_corpus_tools.py::test_score_tab_glossary_expansion -v
```

- [ ] **Step 3: Commit**

```bash
git add profiler/tools/cohort_corpus.py
git commit -m "fix: use set-based glossary matching to prevent false substring matches"
```

---

## Task 5: Create `extract_workbook_codes` Management Command (B1)

**Files:**
- Create: `profiler/management/commands/extract_workbook_codes.py`
- Test: `profiler/tests/test_extract_workbook_codes.py`

- [ ] **Step 1: Create the command**

```python
#!/usr/bin/env python3
"""Extract workbook codes from a drive tree and optionally update corpus config."""

from __future__ import annotations

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Extract workbook codes from drive tree JSON and optionally update config."

    def add_arguments(self, parser):
        parser.add_argument("--drive-tree", required=True, help="Path to drive_tree.json")
        parser.add_argument("--config", required=True, help="Path to cohort_corpus.json")
        parser.add_argument("--update-config", action="store_true", help="Rewrite in_scope_workbooks in config")
        parser.add_argument("--smoke", action="store_true", help="Smoke test mode")

    def handle(self, *args, **options):
        drive_tree_path = Path(options["drive_tree"]).resolve()
        config_path = Path(options["config"]).resolve()

        if options["smoke"]:
            self.stdout.write(self.style.SUCCESS("extract_workbook_codes smoke ok"))
            return

        if not drive_tree_path.exists():
            raise CommandError(f"Drive tree not found: {drive_tree_path}")
        if not config_path.exists():
            raise CommandError(f"Config not found: {config_path}")

        tree = json.loads(drive_tree_path.read_text(encoding="utf-8"))
        config = json.loads(config_path.read_text(encoding="utf-8"))

        regex_str = config.get("workbook_id_regex", r"\\b(\\d{3})\\b")
        try:
            pattern = re.compile(regex_str)
        except re.error as exc:
            raise CommandError(f"Invalid workbook_id_regex: {exc}") from exc

        codes: set[str] = set()

        def walk(node: dict):
            for sheet in node.get("spreadsheets", []):
                name = sheet.get("name", "")
                match = pattern.search(name)
                if match and match.groups():
                    codes.add(match.group(1))
            for sub in node.get("folders", []):
                walk(sub)

        walk(tree)
        sorted_codes = sorted(codes)

        self.stdout.write(f"Found {len(sorted_codes)} workbook code(s):")
        for code in sorted_codes:
            self.stdout.write(f"  {code}")

        if options["update_config"]:
            config["in_scope_workbooks"] = sorted_codes
            bak_path = config_path.with_suffix(".json.bak")
            bak_path.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Updated {config_path} (backup: {bak_path})"))
```

- [ ] **Step 2: Write tests**

```python
import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_extract_workbook_codes_smoke():
    out = StringIO()
    call_command("extract_workbook_codes", drive_tree="/dev/null", config="/dev/null", smoke=True, stdout=out)
    assert "smoke ok" in out.getvalue()


def test_extract_workbook_codes_extracts_codes(tmp_path):
    tree = {
        "folders": [
            {
                "name": "2026",
                "spreadsheets": [
                    {"name": "402 Farm Plan 2026"},
                    {"name": "503 Reference 2026"},
                ],
                "folders": [],
            }
        ],
        "spreadsheets": [],
    }
    tree_path = tmp_path / "drive_tree.json"
    tree_path.write_text(json.dumps(tree), encoding="utf-8")

    config = {"workbook_id_regex": r"\\b(\\d{3})\\b"}
    config_path = tmp_path / "cohort_corpus.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    out = StringIO()
    call_command("extract_workbook_codes", drive_tree=str(tree_path), config=str(config_path), stdout=out)
    output = out.getvalue()
    assert "402" in output
    assert "503" in output


def test_extract_workbook_codes_update_config(tmp_path):
    tree = {
        "folders": [
            {
                "name": "2026",
                "spreadsheets": [{"name": "402 Farm Plan 2026"}],
                "folders": [],
            }
        ],
        "spreadsheets": [],
    }
    tree_path = tmp_path / "drive_tree.json"
    tree_path.write_text(json.dumps(tree), encoding="utf-8")

    config = {"workbook_id_regex": r"\\b(\\d{3})\\b", "in_scope_workbooks": ["OLD"]}
    config_path = tmp_path / "cohort_corpus.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    call_command("extract_workbook_codes", drive_tree=str(tree_path), config=str(config_path), update_config=True)

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated["in_scope_workbooks"] == ["402"]
    assert (config_path.with_suffix(".json.bak")).exists()
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest profiler/tests/test_extract_workbook_codes.py -v
```

- [ ] **Step 4: Commit**

```bash
git add profiler/management/commands/extract_workbook_codes.py profiler/tests/test_extract_workbook_codes.py
git commit -m "feat: add extract_workbook_codes management command"
```

---

## Task 6: Create `validate_domain_context` Management Command (B2)

**Files:**
- Create: `profiler/management/commands/validate_domain_context.py`
- Test: `profiler/tests/test_validate_domain_context.py`

- [ ] **Step 1: Create the command**

```python
#!/usr/bin/env python3
"""Validate domain_context.yaml structure."""

from __future__ import annotations

from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Validate domain_context.yaml structure."

    def add_arguments(self, parser):
        parser.add_argument("--config", required=True, help="Path to domain_context.yaml")
        parser.add_argument("--strict", action="store_true", help="Treat warnings as errors (exit 2)")

    def handle(self, *args, **options):
        config_path = Path(options["config"]).resolve()
        if not config_path.exists():
            raise CommandError(f"Config not found: {config_path}")

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise CommandError("Domain context must be a YAML mapping (dict)")

        errors: list[str] = []
        warnings: list[str] = []

        year_scope = raw.get("year_scope") or {}
        for key in ("active", "archived", "forward"):
            val = year_scope.get(key)
            if val is not None and not (
                isinstance(val, list) and all(isinstance(v, int) for v in val)
            ):
                errors.append(f"year_scope.{key} must be a list of integers")

        if not year_scope.get("active"):
            warnings.append("year_scope.active is empty")

        vocab = raw.get("vocabulary") or {}
        for key in ("operational", "reference", "support", "derived"):
            val = vocab.get(key)
            if val is not None and not (
                isinstance(val, list) and all(isinstance(v, str) for v in val)
            ):
                errors.append(f"vocabulary.{key} must be a list of strings")

        if not any(vocab.get(k) for k in ("operational", "reference", "support", "derived")):
            warnings.append("vocabulary has no tokens")

        dedup = raw.get("deduplication") or {}
        strategy = dedup.get("strategy", "latest_year")
        if strategy not in ("latest_year", "none"):
            errors.append(f"deduplication.strategy must be 'latest_year' or 'none', got {strategy!r}")

        glossary = raw.get("glossary") or {}
        if not isinstance(glossary, dict):
            errors.append("glossary must be a mapping")
        elif glossary and not all(isinstance(k, str) and isinstance(v, str) for k, v in glossary.items()):
            errors.append("glossary keys and values must be strings")

        for err in errors:
            self.stdout.write(self.style.ERROR(f"ERROR: {err}"))
        for warn in warnings:
            self.stdout.write(self.style.WARNING(f"WARNING: {warn}"))

        if errors:
            raise CommandError(f"Validation failed with {len(errors)} error(s)")

        self.stdout.write(self.style.SUCCESS("Domain context is valid"))

        if warnings and options["strict"]:
            raise CommandError(f"Validation failed with {len(warnings)} warning(s) (strict mode)")
```

- [ ] **Step 2: Write tests**

```python
import pytest
from io import StringIO
from pathlib import Path
from django.core.management import call_command
from django.core.management.base import CommandError


def test_validate_domain_context_valid(tmp_path):
    ctx = tmp_path / "domain_context.yaml"
    ctx.write_text(
        "year_scope:\n  active: [2025, 2026]\nvocabulary:\n  operational: [planting]\n",
        encoding="utf-8",
    )
    out = StringIO()
    call_command("validate_domain_context", config=str(ctx), stdout=out)
    assert "valid" in out.getvalue()


def test_validate_domain_context_missing_file():
    with pytest.raises(CommandError, match="not found"):
        call_command("validate_domain_context", config="/nonexistent.yaml")


def test_validate_domain_context_bad_year_type(tmp_path):
    ctx = tmp_path / "domain_context.yaml"
    ctx.write_text("year_scope:\n  active: [\"2025\"]\n", encoding="utf-8")
    out = StringIO()
    with pytest.raises(CommandError, match="ERROR"):
        call_command("validate_domain_context", config=str(ctx), stdout=out)


def test_validate_domain_context_strict_warning(tmp_path):
    ctx = tmp_path / "domain_context.yaml"
    ctx.write_text("year_scope:\n  active: [2025]\n", encoding="utf-8")
    out = StringIO()
    with pytest.raises(CommandError, match="strict"):
        call_command("validate_domain_context", config=str(ctx), strict=True, stdout=out)
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest profiler/tests/test_validate_domain_context.py -v
```

- [ ] **Step 4: Commit**

```bash
git add profiler/management/commands/validate_domain_context.py profiler/tests/test_validate_domain_context.py
git commit -m "feat: add validate_domain_context management command"
```

---

## Task 7: Create `draft_domain_context` Management Command (B3)

**Files:**
- Create: `profiler/management/commands/draft_domain_context.py`
- Test: `profiler/tests/test_draft_domain_context.py`

- [ ] **Step 1: Create the command**

```python
#!/usr/bin/env python3
"""Draft a domain_context.yaml from drive tree and optional raw notes."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand, CommandError

_STARTER_KEYWORDS = {
    "operational": ["planting", "harvest", "order", "sale", "purchase", "delivery"],
    "reference": ["variety", "crop", "farm", "field", "block", "customer", "product"],
    "support": ["index", "lookup", "validation", "helper", "config"],
    "derived": ["summary", "pivot", "rollup", "total", "report", "dashboard"],
}

_YEAR_RE = re.compile(r"\b(20\d{2})\b")


class Command(BaseCommand):
    help = "Draft domain_context.yaml from drive tree and optional raw notes."

    def add_arguments(self, parser):
        parser.add_argument("--drive-tree", required=True, help="Path to drive_tree.json")
        parser.add_argument("--raw-notes-dir", default=None, help="Directory with .md/.txt raw notes")
        parser.add_argument("--out", default=None, help="Output path (default: stdout)")
        parser.add_argument("--smoke", action="store_true", help="Smoke test mode")

    def handle(self, *args, **options):
        if options["smoke"]:
            self.stdout.write(self.style.SUCCESS("draft_domain_context smoke ok"))
            return

        tree_path = Path(options["drive_tree"]).resolve()
        if not tree_path.exists():
            raise CommandError(f"Drive tree not found: {tree_path}")

        tree = json.loads(tree_path.read_text(encoding="utf-8"))

        years: set[int] = set()
        codes: set[str] = set()

        def walk(node: dict):
            name = node.get("name", "")
            for m in _YEAR_RE.finditer(name):
                years.add(int(m.group(1)))
            for sheet in node.get("spreadsheets", []):
                sheet_name = sheet.get("name", "")
                for m in _YEAR_RE.finditer(sheet_name):
                    years.add(int(m.group(1)))
            for sub in node.get("folders", []):
                walk(sub)

        walk(tree)
        sorted_years = sorted(years)

        if len(sorted_years) >= 2:
            active_years = sorted_years[-2:]
            archived_years = sorted_years[:-2]
        else:
            active_years = sorted_years
            archived_years = []

        vocabulary = {k: [] for k in _STARTER_KEYWORDS}

        raw_notes_dir = options.get("raw_notes_dir")
        if raw_notes_dir:
            raw_path = Path(raw_notes_dir).resolve()
            if raw_path.exists():
                all_words: list[str] = []
                for fp in raw_path.rglob("*"):
                    if fp.is_file() and fp.suffix in (".md", ".txt"):
                        text = fp.read_text(encoding="utf-8", errors="ignore")
                        words = re.findall(r"[a-zA-Z]{3,}", text.lower())
                        all_words.extend(words)

                freq = Counter(all_words)
                for category, starters in _STARTER_KEYWORDS.items():
                    hits = [(word, count) for word, count in freq.most_common(200) if word in starters]
                    vocabulary[category] = [word for word, _count in hits[:5]]

        payload = {
            "_documentation": {
                "generated": "draft — review required",
                "domain": "Short slug for the business domain",
                "year_scope": "Populate from drive tree inspection",
            },
            "domain": "",
            "description": "",
            "year_scope": {
                "active": active_years,
                "archived": archived_years,
                "forward": [],
            },
            "deduplication": {
                "strategy": "latest_year",
                "exceptions": [
                    {"tab_title": "", "reason": ""}
                ],
            },
            "entities": [],
            "vocabulary": vocabulary,
            "glossary": {},
            "scope_notes": "",
        }

        yaml_text = yaml.dump(payload, default_flow_style=False, sort_keys=False, allow_unicode=True)

        out_path = options.get("out")
        if out_path:
            Path(out_path).write_text(yaml_text, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Draft written to {out_path}"))
        else:
            self.stdout.write(yaml_text)
```

- [ ] **Step 2: Write tests**

```python
import pytest
from io import StringIO
from pathlib import Path
from django.core.management import call_command
from django.core.management.base import CommandError


def test_draft_domain_context_smoke():
    out = StringIO()
    call_command("draft_domain_context", drive_tree="/dev/null", smoke=True, stdout=out)
    assert "smoke ok" in out.getvalue()


def test_draft_domain_context_basic(tmp_path):
    tree = {
        "name": "Farm Root",
        "folders": [
            {
                "name": "2025",
                "spreadsheets": [{"name": "402 Plan 2025"}],
                "folders": [],
            },
            {
                "name": "2026",
                "spreadsheets": [{"name": "402 Plan 2026"}],
                "folders": [],
            },
        ],
        "spreadsheets": [],
    }
    tree_path = tmp_path / "drive_tree.json"
    tree_path.write_text(json.dumps(tree), encoding="utf-8")

    out = StringIO()
    call_command("draft_domain_context", drive_tree=str(tree_path), stdout=out)
    output = out.getvalue()
    assert "2025" in output
    assert "2026" in output
    assert "draft" in output


def test_draft_domain_context_missing_file():
    with pytest.raises(CommandError, match="not found"):
        call_command("draft_domain_context", drive_tree="/nonexistent.json")
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest profiler/tests/test_draft_domain_context.py -v
```

- [ ] **Step 4: Commit**

```bash
git add profiler/management/commands/draft_domain_context.py profiler/tests/test_draft_domain_context.py
git commit -m "feat: add draft_domain_context management command"
```

---

## Task 8: Update Makefile Targets (B4)

**Files:**
- Modify: `workbook/makefile_targets.py`

- [ ] **Step 1: Add new targets to `phonies` and `full_targets_block`**

In `phonies()`, add to the list:

```python
"draft-domain-context",
"validate-domain-context",
"extract-workbook-codes",
"orient",
```

Add new block functions before `full_targets_block`:

```python
def draft_domain_context_block(ctx: MakeContext) -> str:
    return (
        "draft-domain-context:\n"
        + _indent(
            '$(MANAGE) draft_domain_context '
            '--drive-tree "$${DRIVE_FOLDER_OUT:-data/profile_snapshots/drive_tree.json}" '
            '--out config/domain_context.yaml'
        )
        + "\n\n"
    )


def validate_domain_context_block(ctx: MakeContext) -> str:
    return (
        "validate-domain-context:\n"
        + _indent('$(MANAGE) validate_domain_context --config config/domain_context.yaml')
        + "\n\n"
    )


def extract_workbook_codes_block(ctx: MakeContext) -> str:
    return (
        "extract-workbook-codes:\n"
        + _indent(
            '$(MANAGE) extract_workbook_codes '
            '--drive-tree "$${DRIVE_FOLDER_OUT:-data/profile_snapshots/drive_tree.json}" '
            '--config config/cohort_corpus.json '
            '--update-config'
        )
        + "\n\n"
    )


def orient_block(ctx: MakeContext) -> str:
    return "orient: validate-domain-context profile-drive-folder extract-workbook-codes\n\n"
```

In `full_targets_block`, add the new blocks:

```python
def full_targets_block(ctx: MakeContext) -> str:
    parts = [
        variables_block(ctx),
        "\n",
        codegen_tooling_block(ctx),
        "\n",
        draft_domain_context_block(ctx),
        validate_domain_context_block(ctx),
        extract_workbook_codes_block(ctx),
        orient_block(ctx),
        generate_models_block(ctx),
        # ... rest unchanged
    ]
    return "".join(parts)
```

- [ ] **Step 2: Verify syntax by importing the module**

```bash
.venv/bin/python -c "from workbook.makefile_targets import full_targets_block, MakeContext; print(full_targets_block(MakeContext())[:500])"
```

- [ ] **Step 3: Commit**

```bash
git add workbook/makefile_targets.py
git commit -m "feat: add orient, draft-domain-context, validate-domain-context, extract-workbook-codes Makefile targets"
```

---

## Task 9: Update AGENTS.md Template (C2)

**Files:**
- Modify: `scripts/new_product.py:583-657`

- [ ] **Step 1: Replace Phase 0 paragraph in `_render_agents_profile_section`**

Replace lines 603-615 (the Phase 0 paragraph):

```python
#### Phase 0 — Orient

Run these commands in order. Each is safe to re-run.

1. **Draft domain context** (optional seed from drive tree):
   ```bash
   make draft-domain-context
   ```
2. **Edit** `config/domain_context.yaml` — set year scope, vocabulary, glossary.
3. **Validate** the domain context file:
   ```bash
   make validate-domain-context
   ```
4. **Profile the drive folder**:
   ```bash
   make profile-drive-folder
   ```
5. **Extract workbook codes** into `config/cohort_corpus.json`:
   ```bash
   make extract-workbook-codes
   ```
6. Review `config/cohort_corpus.json` — adjust heuristics before Phase 1.
```

- [ ] **Step 2: Commit**

```bash
git add scripts/new_product.py
git commit -m "docs: update AGENTS.md Phase 0 template with executable orient checklist"
```

---

## Task 10: Update Example Files (C3)

**Files:**
- Modify: `example_data/domain_context.example.yaml`
- Create: `example_data/drive_tree.example.json`

- [ ] **Step 1: Update `domain_context.example.yaml`**

Replace the entire file with:

```yaml
_documentation:
  domain: "Short slug for the business domain"
  year_scope.active: "Years to profile in full (list of ints)"
  deduplication.strategy: "latest_year | none"
  deduplication.exceptions: "Tabs that should be profiled across all years"

domain: ""
description: ""

year_scope:
  active: []
  archived: []
  forward: []

deduplication:
  strategy: latest_year
  exceptions:
    - tab_title: "Sales Actuals"
      reason: "Structure changes yearly; profile all years"

entities: []

vocabulary:
  operational: []
  reference: []
  support: []
  derived: []

glossary: {}

scope_notes: ""
```

- [ ] **Step 2: Create `example_data/drive_tree.example.json`**

```json
{
  "name": "Farm Root",
  "folders": [
    {
      "name": "2025",
      "folders": [],
      "spreadsheets": [
        {"id": "sheet-402-2025", "name": "402 Farm Plan 2025", "tabs": [{"title": "Crop Planner"}]}
      ],
      "other_files": []
    },
    {
      "name": "2026",
      "folders": [],
      "spreadsheets": [
        {"id": "sheet-402-2026", "name": "402 Farm Plan 2026", "tabs": [{"title": "Crop Planner"}]}
      ],
      "other_files": []
    }
  ],
  "spreadsheets": [],
  "other_files": []
}
```

- [ ] **Step 3: Commit**

```bash
git add example_data/domain_context.example.yaml example_data/drive_tree.example.json
git commit -m "docs: improve domain_context example and add drive_tree example"
```

---

## Task 11: Update Chassis Gate (C1)

**Files:**
- Modify: `Makefile:145-178`

- [ ] **Step 1: Add domain context smoke tests to `chassis-gate`**

After the `profile_coda_corpus` smoke line (around line 160), add:

```makefile
	# Domain context integration smoke
	DB_ENGINE=sqlite $(MANAGE) validate_domain_context --config example_data/domain_context.example.yaml
	DB_ENGINE=sqlite $(MANAGE) draft_domain_context --drive-tree example_data/drive_tree.example.json --smoke
	DB_ENGINE=sqlite $(MANAGE) extract_workbook_codes --drive-tree example_data/drive_tree.example.json --config example_data/cohort_corpus.example.json --smoke
```

- [ ] **Step 2: Run the specific new gate steps**

```bash
DB_ENGINE=sqlite .venv/bin/python manage.py validate_domain_context --config example_data/domain_context.example.yaml
DB_ENGINE=sqlite .venv/bin/python manage.py draft_domain_context --drive-tree example_data/drive_tree.example.json --smoke
DB_ENGINE=sqlite .venv/bin/python manage.py extract_workbook_codes --drive-tree example_data/drive_tree.example.json --config example_data/cohort_corpus.example.json --smoke
```

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "ci: add domain context commands to chassis gate smoke tests"
```

---

## Task 12: Add `--dry-run` to `profile_cohort_corpus` (4.5)

**Files:**
- Modify: `profiler/management/commands/profile_cohort_corpus.py`
- Modify: `profiler/tools/cohort_corpus.py`

- [ ] **Step 1: Add CLI flag**

In `profiler/management/commands/profile_cohort_corpus.py`, add to `add_arguments`:

```python
parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Preview the run without making API calls or writing deep artifacts",
)
```

Pass it through to `run_cohort_corpus`:

```python
run_cohort_corpus(
    # ... existing args ...
    dry_run=options.get("dry_run", False),
)
```

- [ ] **Step 2: Add `dry_run` parameter to `run_cohort_corpus`**

Signature change:

```python
def run_cohort_corpus(
    *,
    # ... existing args ...
    dry_run: bool = False,
) -> dict:
```

In the deep-profiling section, wrap the actual fetch/write logic:

```python
if dry_run:
    dry_run_preview = {
        "mode": "dry_run",
        "estimated_api_calls": len(index_records) * sum(len(tabs) for tabs in approved_tabs.values()),
        "estimated_deep_jobs": sum(len(approved_tabs.get(rec["workbook_code"], [])) for rec in index_records),
        "workbooks": [
            {
                "code": wb,
                "year_list": sorted({rec.get("year") for rec in index_records if rec["workbook_code"] == wb}),
                "tab_count": len(tabs),
            }
            for wb, tabs in approved_tabs.items()
        ],
        "warnings": [],
    }
    if domain_context is None:
        dry_run_preview["warnings"].append("No domain context loaded")
    artifacts["dry_run_preview"] = str(out_dir / f"dry_run_preview_{date_stamp}.json")
    write_json(out_dir / f"dry_run_preview_{date_stamp}.json", dry_run_preview)
    return artifacts
```

- [ ] **Step 3: Write test**

Add to `profiler/tests/test_cohort_corpus_tools.py`:

```python
def test_run_cohort_corpus_dry_run(tmp_path: Path):
    corpus_out_dir = tmp_path / "corpus_run"
    corpus_out_dir.mkdir(parents=True, exist_ok=True)
    date_stamp = "2026-05-20"

    workbook_index_payload = {
        "generated_from": f"drive_discovery_{date_stamp}.json",
        "record_count": 1,
        "records": [
            {"year": 2026, "workbook_code": "402", "spreadsheet_id": "s1", "spreadsheet_name": "402 2026"},
        ],
    }
    index_path = corpus_out_dir / f"in_scope_workbook_index_{date_stamp}.json"
    index_path.write_text(json.dumps(workbook_index_payload), encoding="utf-8")

    broad_payload = {
        "run_count": 1,
        "success_count": 1,
        "failure_count": 0,
        "results": [],
        "inventory_rows": [
            {"spreadsheet_id": "s1", "sheet_id": 0, "rows": 100, "cols": 10, "tab_title": "Plan Board"},
        ],
    }
    broad_path = corpus_out_dir / f"broad_profile_coverage_{date_stamp}.json"
    broad_path.write_text(json.dumps(broad_payload), encoding="utf-8")

    selection_path = corpus_out_dir / f"tab_selection_{date_stamp}.json"
    selection_path.write_text(
        json.dumps({"approved_tabs": {"402": ["Plan Board"]}}),
        encoding="utf-8",
    )

    corpus_config = {"folder_id": "drive-folder-1", "in_scope_workbooks": ["402"]}
    mock_drive = MagicMock()
    mock_sheets = MagicMock()

    outputs = run_cohort_corpus(
        drive_service=mock_drive,
        sheets_service=mock_sheets,
        config=corpus_config,
        out_dir=corpus_out_dir,
        date_stamp=date_stamp,
        resume_from_tab_selection=True,
        dry_run=True,
    )

    assert "dry_run_preview" in outputs
    preview = json.loads(
        (corpus_out_dir / f"dry_run_preview_{date_stamp}.json").read_text(encoding="utf-8")
    )
    assert preview["mode"] == "dry_run"
    assert preview["estimated_deep_jobs"] >= 1
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest profiler/tests/test_cohort_corpus_tools.py::test_run_cohort_corpus_dry_run -v
```

- [ ] **Step 5: Commit**

```bash
git add profiler/management/commands/profile_cohort_corpus.py profiler/tools/cohort_corpus.py profiler/tests/test_cohort_corpus_tools.py
git commit -m "feat: add --dry-run mode to profile_cohort_corpus"
```

---

## Task 13: Final Integration — Run Full Chassis Gate

**Files:**
- All modified files

- [ ] **Step 1: Run ruff**

```bash
.venv/bin/ruff check profiler/management/commands/extract_workbook_codes.py profiler/management/commands/validate_domain_context.py profiler/management/commands/draft_domain_context.py profiler/tools/domain_context.py profiler/tools/cohort_corpus.py workbook/makefile_targets.py scripts/new_product.py
.venv/bin/ruff format profiler/management/commands/extract_workbook_codes.py profiler/management/commands/validate_domain_context.py profiler/management/commands/draft_domain_context.py profiler/tools/domain_context.py profiler/tools/cohort_corpus.py workbook/makefile_targets.py scripts/new_product.py
```

- [ ] **Step 2: Run full test suite**

```bash
DB_ENGINE=sqlite .venv/bin/pytest profiler/tests/test_domain_context.py profiler/tests/test_cohort_corpus_tools.py profiler/tests/test_extract_workbook_codes.py profiler/tests/test_validate_domain_context.py profiler/tests/test_draft_domain_context.py -v
```

- [ ] **Step 3: Run chassis gate subset**

```bash
make check
DB_ENGINE=sqlite .venv/bin/python manage.py validate_domain_context --config example_data/domain_context.example.yaml
DB_ENGINE=sqlite .venv/bin/python manage.py draft_domain_context --drive-tree example_data/drive_tree.example.json --smoke
DB_ENGINE=sqlite .venv/bin/python manage.py extract_workbook_codes --drive-tree example_data/drive_tree.example.json --config example_data/cohort_corpus.example.json --smoke
```

- [ ] **Step 4: Commit any ruff fixes**

```bash
git add -A
git commit -m "style: ruff format for pre-farm hardening" || echo "No changes to commit"
```

---

## Task 14: Final Commit to Master

- [ ] **Step 1: Review git log**

```bash
git log --oneline -15
```

- [ ] **Step 2: Commit all remaining changes**

```bash
git add -A
git commit -m "feat: comprehensive pre-farm launch hardening

- fix: simplify deduplicate_index_records to year-only filter
- fix: move tab-level dedup to deep loop with dedup trace
- fix: populate known_tabs in full mode
- fix: normalize legacy coverage bonus to >=2 years
- fix: set-based glossary matching for substring safety
- feat: extract_workbook_codes management command
- feat: validate_domain_context management command
- feat: draft_domain_context management command
- feat: orient Makefile target and sub-targets
- feat: --dry-run mode for profile_cohort_corpus
- docs: update AGENTS.md Phase 0 with executable checklist
- docs: improve domain_context.example.yaml
- ci: add domain context commands to chassis gate
- chore: add example_data/drive_tree.example.json"
```

- [ ] **Step 3: Push to master**

```bash
git push origin master
```
