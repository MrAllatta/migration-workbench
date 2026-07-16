# BUG-001: `.omo/` agent-harness directory leaked into core workbench runtime

## Status

Under review. Found during CI triage after lint/format gate fixes.

## Severity

High — CI gate failure on clean checkout; architecture boundary violation.

## Symptom

`make chassis-gate` fails in CI with:

```
FAILED workbook/tests/test_queue_protocol.py::TestFindOmoRoot::test_finds_omo_root_from_repo_root
FileNotFoundError: No .omo/ directory found. Run from a workbench or product repo root.
```

Locally the test passes because `.omo/` exists as a harness-local directory, but `.omo` is in `.gitignore` and is not present in a CI checkout.

## Root cause

The `.omo/` directory is the agent harness workspace. Core workbench code and CLI commands treat it as a runtime dependency:

- `workbook/tools/queue_protocol.py` — defines `find_omo_root()` and walks up from CWD looking for `.omo/`.
- `deployment/commands/ecosystem.py` — `wb ecosystem health` and `wb ecosystem ack` call `find_omo_root()` to locate queue directories.
- `workbook/tests/test_queue_protocol.py::TestFindOmoRoot::test_finds_omo_root_from_repo_root` — asserts `.omo/` exists at repo root.

This is an architecture leak: product repos installing `migration-workbench` from PyPI will not have `.omo/` unless the agent harness has created it. The `wb ecosystem` commands and queue protocol cannot function as shipped.

## Affected files

| File | Role |
|------|------|
| `workbook/tools/queue_protocol.py` | Defines `find_omo_root()`, `_QUEUE_ROOT`, `list_queue_entries()` |
| `deployment/commands/ecosystem.py` | Calls `find_omo_root()` for `health`/`ack` subcommands |
| `scripts/new_product.py` | Mentions `.omo/protocol.md` as a harness doc (doc only) |

## Reproduction

```bash
# In a clean clone without .omo/
rm -rf .omo
.venv/bin/python -m pytest workbook/tests/test_queue_protocol.py::TestFindOmoRoot::test_finds_omo_root_from_repo_root -v
```

## Recommended fix

1. **Remove `.omo/` assumption from core runtime.** Queue protocol should accept an explicit `--base-path` / `OMO_ROOT` env var and default to the current working directory or a documented product-repo directory, not a hidden harness directory.
2. **Move harness-specific queue logic to `.pi/extensions/session-harness/`** or a similar extension package if it is only used by the agent harness.
3. **Update tests** to create a temporary `.omo/` directory under `tmp_path` rather than relying on the repo root.
4. If `wb ecosystem` is intended to be a public CLI, it should not require `.omo/`; if it is an internal harness command, it should live in the extension.

## Decision needed

- Is `wb ecosystem` a public workbench CLI feature or an agent-harness internal?
- Is the queue protocol a core library feature or a harness plugin concern?

Until decided, gate can be unblocked by marking `test_finds_omo_root_from_repo_root` with `@pytest.mark.skipif(not (Path.cwd() / ".omo").is_dir(), reason="requires harness .omo/")`.
