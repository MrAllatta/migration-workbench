# 0.7.x Issue Hardening (Issues #4-#13)

**Date:** 2026-05-14
**Status:** Approved (pending implementation plan)

## Summary

This spec defines a targeted hardening patchset for the 0.7.x line, covering GitHub issues #4 through #13. The focus is to make contract authoring and codegen safer and more composable without introducing a new contract toolchain or a new schema version.

## Scope

In-scope work is exactly the following issues:

1. #4: `generate_models` / scaffold workflow silently auto-committed files
1. #5: `validate_contract_tables` skips FK validation for `extra_fields` (designed models)
1. #6: `corpus-codegen-report` fails on design-review warnings
1. #7: `generate_admin` should work without view manifest (designed models)
1. #8: preserve declaration order when rendering `extra_fields`
1. #9: per-table suppression of design-review warnings
1. #10: support mixing scaffolded v1.0 tables with v1.3 designed models in one contract
1. #11: document `choices` kwarg format and accept common authoring mistake
1. #12: `--force` backups (`.bak`) interfere with imports and git tracking
1. #13: compose contracts by merging table lists from separate files

## Goals

1. Contract composition must support splitting large `tables:` lists across files, including designed model fragments, without manual copying.
1. Codegen and scaffolding must never create git commits in an existing repository without explicit operator action.
1. Validation and review must treat designed models as first-class: FK checks must apply equally to `columns[]` and `extra_fields`.
1. Code generation must stop producing `.bak` sidecar files by default; diffs should be produced via `--diff` and via git.
1. Product-scaffold Makefile targets must match actual command capabilities (manifest optional, contract review can be report-only).

## Non-goals

1. No new contract schema version.
1. No new standalone contract CLI suite beyond minimal flags needed for the existing `wb contract review`.
1. No attempt to change generator formatting beyond what is required to satisfy the filed issues.

## Design

### Issue #13: `!include_list` for list splicing into `tables`

Add a new YAML tag `!include_list` to the contract loader.

Constraints:

1. The included file must be a YAML list (sequence) of table dicts.
1. The tag is used inside the `tables:` list, e.g.

```yaml
version: "1.3"
tables:
  - suggested_model_name: planting
    source_tab: null
    extra_fields: { ... }
  - !include_list profiled-tables.yaml
  - !include_list designed-models.yaml
```

Loader behavior:

1. `!include_list path.yaml` loads YAML from `path.yaml` relative to the including file.
1. The constructor returns the loaded list value.
1. `load_contract()` flattens `tables` so any nested lists are spliced into the final `tables` list.
1. Cyclic include detection applies equally to `!include` and `!include_list`.

Rationale:

1. YAML-native contract composition with minimal new surface area.
1. Enables issue #10 directly (mixing profiled tables and designed models).

### Issue #10: mixing v1.0 scaffolded tables with v1.3 designed models

No new command is introduced. Instead, composition becomes the primary workflow:

1. Keep profiled tables in a separate file (typically produced by scaffolding).
1. Keep designed models in a separate file (from `scaffold_designed_model`).
1. A top-level `contract.yaml` includes both via `!include_list`.

Note: `load_contract()` already permits versions `1.0` through `1.3`. The top-level contract should specify `version: "1.3"` when mixing designed models.

### Issue #9: per-table suppression of design-review warnings

Add an optional per-table key:

```yaml
suppress_review_warnings:
  - multiple_fk_without_unique
```

Rule IDs:

1. Implement at least `multiple_fk_without_unique`.
1. Rule IDs are stable strings used for suppression matching.

Behavior:

1. `wb contract review` continues to compute issues as today.
1. Before returning issues, filter out suppressed issues for each table based on rule ID.
1. Filtering is strictly per-table; there is no global suppression list.

### Issue #8: preserve `extra_fields` declaration order

When rendering resolved fields (`get_fields()`), iterate `extra_fields` in insertion order (as loaded from YAML) rather than sorting.

Rationale:

1. Generated models should read like hand-authored models.
1. Contract authors can explicitly choose field ordering by writing YAML in that order.

### Issue #5: validate FK targets for `extra_fields` (designed models)

Change `validate_contract_tables()` FK target validation to use the resolved field list (`get_fields(table)`) instead of only `table["columns"]`.

Validation rule:

1. For any field where `class` is `models.ForeignKey`, validate its `to` target is either `self` or a model present in the contract table list.
1. Validation warnings remain warnings (non-fatal), consistent with current behavior.

### Issue #12: remove `.bak` backups from generators

Change `generate_models` and `generate_admin`:

1. When `--force` is used, overwrite the output file in place without renaming to `.bak`.
1. Continue to support `--diff` for previewing changes.

Rationale:

1. `.bak` python files can be imported accidentally and break Django startup.
1. `.bak` files pollute git status and can be committed by mistake.

### Issue #4: never auto-commit when scaffolding into an existing git repo

`scripts/new_product.py` currently runs `git add -A` and `git commit ...` even if the output directory is already a git repo.

Required behavior:

1. If scaffolding created a new repo via `git init`, perform the initial commit (as today).
1. If the output directory is already a git repo, do not run `git add` or `git commit`.
1. Print a clear message indicating the scaffold wrote files but did not commit because the repo already existed.

### Issue #6: keep `wb contract review` failing by default; add `--exit-zero`

Keep the current exit code semantics:

1. When issues are found, `wb contract review` exits non-zero.

Add a flag:

1. `--exit-zero`: always return exit code 0, while still printing issues.

Update the scaffolded product Makefile target `corpus-codegen-report` to use `--exit-zero` so it remains a report rather than a gate.

### Issue #7: allow admin generation without a view manifest in product scaffolds

The underlying management command already supports omitting `--manifest`.

Update the scaffolded product Makefile:

1. Remove the `test -f view-manifest.yaml` hard guard.
1. Pass `--manifest` only when the manifest file exists.
1. Keep `generate-view-manifest` as the explicit target to create the manifest when bundle structure exists.

### Issue #11: document `choices` format and accept `EnumName.choices`

Documentation:

1. Document that contract `kwargs.choices` should be the bare enum class name (e.g. `EventType`), not `EventType.choices`.

Robustness:

1. If the contract specifies `choices: "EventType.choices"`, normalize it to `EventType` during rendering so the output is still `choices=EventType.choices`.

## Compatibility

1. Existing contracts remain valid; new keys/tags are optional.
1. `!include` continues to behave as-is.
1. `!include_list` is additive.
1. Removing `.bak` creation changes `make diff-generated` expectations; any docs referencing `.bak` must be updated to prefer `--diff` and git.

## Testing

Add/extend tests to cover:

1. Contract loader supports `!include_list` and flattens `tables` correctly.
1. FK validation warns for missing FK targets in `extra_fields`.
1. `suppress_review_warnings` filters `multiple_fk_without_unique` per table.
1. `extra_fields` order is preserved end-to-end (load contract -> render models -> field order stable).
1. Generators overwrite without producing `.bak` files.
1. `wb contract review --exit-zero` exits 0 even with issues.
1. Product scaffold Makefile changes (snapshot test) for `corpus-codegen-report` and `generate-admin` behavior.
1. Scaffolding into an existing git repo does not create new commits.

## Release Notes (0.7.x)

1. Contract YAML: add `!include_list` for composing `tables` from list fragments.
1. Contract review: add `suppress_review_warnings` per table and `wb contract review --exit-zero`.
1. Codegen: preserve `extra_fields` order; remove `.bak` sidecar backups.
1. Validation: FK target validation now applies to `extra_fields`.
1. Scaffolding: no silent git commits when scaffolding into an existing repo.
