# Agent notes

## Repo identity

This is **migration-workbench** — a Python package (PyPI: `migration-workbench`) providing five Django apps (connectors, profiler, importer, workbook, deployment) that scaffolded product repos install as a dependency. The root `manage.py` and `migration_workbench/settings.py` are for development and CI. Product repos bring their own.

## Worktree Model

`~/projects/migration-workbench` always has `master` checked out. Period.
Every feature, bugfix, or mission gets its own worktree under `.worktrees/`.

### Lifecycle

1. **Create:** `git worktree add .worktrees/wt-<slug> -b feat/<slug>`
   - Worktree name: `wt-<slug>` (matches mission/brief slug)
   - Branch name: `feat/<slug>` (Conventional Commits prefix)
   - Slug comes from brief filename or mission name

2. **Work:** All development, testing, and gating happens inside the worktree.
   - Run `make chassis-gate` from the worktree
   - Commit checkpoints on the feature branch
   - Never touch `~/projects/migration-workbench` directly

3. **Merge:** Squash-merge back to master when gate is green.
   ```bash
   cd ~/projects/migration-workbench
   git merge --squash .worktrees/wt-<slug>
   git commit -m "<conventional message>"
   ```

4. **Cleanup:** Remove worktree and branch after merge.
   ```bash
   git worktree remove .worktrees/wt-<slug>
   git branch -D feat/<slug>   # -D required: squash merge creates a new commit hash
   ```

   Note: `git branch -d` will refuse because the branch's commits are not ancestrally
   connected to `master` — only their *content* was squashed. `-D` is correct here. See
   [git-merge(1) --squash](https://git-scm.com/docs/git-merge#_squash_mode).

### Rules

- No exceptions. Even "quick fixes" get a worktree.
- If `.worktrees/wt-<slug>` already exists, check for stale worktrees first.
- Never commit directly to `master` from a worktree.
- Never push from a worktree without explicit human delegation.

## Quality Gates

`make chassis-gate` is the authoritative gate. PRs must pass it.

### Gates

| Gate | Command | When |
|------|---------|------|
| Full CI | `make chassis-gate` | Before every merge to master |
| Single test | `.venv/bin/python -m pytest <path>::<name>` | During development |
| Doc coverage | `make doc-coverage` | Before merge (80% enforced) |
| Format | `make format` | Before commit |

### Rules

- Never merge to master if gate is red.
- Never tag a commit the public CI has not seen pass.
- If gate fails, fix it before `make finish`.
- For known-red WIP, use `git commit` with `[WIP]` prefix, not `make finish`.

## Versioning

Two versions, never one. They move independently.

| Version | Location | Signals |
|---------|----------|---------|
| Package release | `pyproject.toml` `version` | PyPI release |
| Schema checkpoint | `PipelineState.version` | Format change requiring migration |

### Rules

- Never conflate the two. A schema version bump ≠ package version bump.
- Patch = unit-tested, gate green. Not validated against real data.
- Minor = product capability proven end-to-end against real data.
- 1.0.0 = both engagements retired, consultant playbook proven.
- Merge to master = release. Every merge that changes user-facing behavior gets a tag.
- Changelog: updated at bottom of `README.md`.

## Push Authority

The human owns the push to `origin/master` and release tags.

### Rules

- Agents commit, merge, and tag locally. Never push without explicit delegation.
- If human delegates push authority for a specific release, agent may push.
- Feature branches may be pushed freely as backup (not PRs).
- PyPI uploads blocked until 1.0.0 (PyPI blocks `<= 0.9.3`).

## Architecture

Five Django apps. This repo is upstream. Product repos consume via PyPI.

### Apps

| App | Responsibility | Entry points |
|-----|---------------|--------------|
| connectors | Provider adapters (Google Sheets, Coda) | `connectors/base.py`, `connectors/router.py` |
| profiler | Read-only source inspection, PipelineState | `profiler/tools/pipeline_state.py` |
| importer | `BaseImportCommand` chassis, preflight/apply | `importer/base.py`, `importer/chassis.py` |
| workbook | Schema contract, codegen, view manifest | `workbook/management/commands/` |
| deployment | Manifest validation, `wb` CLI, release store | `deployment/wb_cli.py`, `deployment/manifest.py` |

### Patching Boundary

| Situation | Where to fix |
|-----------|-------------|
| Bug in workbench command, template, or utility | **Here** |
| Missing feature another product would need | **Here** |
| Product-specific display logic or admin config | **Product repo** |
| Product-specific data validation or business rules | **Product repo** |

Never vendor workbench code into a product repo. Fix upstream, release to PyPI, bump the pin.

## Interface contract

The Makefile loads `.env` via `-include .env` and uses bare `export` (line 2), which makes **all** `.env` variables available in recipe shells. This is the load-and-export contract: the Makefile is responsible for making variables available to its recipes, and it fails clearly when a required variable is missing.

- Call `make <target>` without explicit env var overrides. The Makefile handles its own configuration.
- If a target needs a variable, it will tell you. `$${VAR:?required}` returns an error naming the missing variable. `$${VAR:-default}` provides a fallback. Don't pre-empt that contract by passing variables the Makefile already loads.
- `make <target> VAR=value` overrides are appropriate only when the Makefile uses `$(VAR)` (Make variable syntax, rounded braces). `$${VAR}` (double-dollar shell syntax) means the Makefile expects it from `.env`.

Product repos use selective `export VAR` instead of bare `export`. Same principle applies: trust the Makefile to load what it needs.

When calling management commands directly (not through Make), source `.env` first:

```bash
set -a; . .env; set +a; python manage.py <command>
```

Or use `make bash` to enter a shell with `.env` loaded.

## Naming & style

### Naming rules

Never use single-letter names, alphabetic slice labels, or abstract positional placeholders.

| Banned | Use instead |
|--------|-------------|
| `A`, `B`, `C`, `D` (standalone labels) | `source_contract`, `target_manifest`, `bundle_config`, `schema_contract` |
| `x`, `y`, `n`, `m`, `i` (loop/scratch) | `tab_row`, `column_entry`, `field_name`, `row_index`, `tab_count` |
| `tmp`, `res`, `val`, `obj` | `parsed_date`, `contract_dict`, `field_slug`, `worksheet_tab` |
| Type vars `T`, `K`, `V` | `RowT`, `ModelT`, `ConfigT`, `KeyT`, `ValueT` |

### Domain vocabulary

| Concept | Preferred names |
|---------|-----------------|
| Normalised source data | `bundle`, `bundle_tab`, `tab_row`, `bundle_config` |
| Profiler output | `profile_doc`, `doc_profile`, `column_profile`, `profiler_output` |
| Structural map | `structure`, `structure_artifact`, `tab_entry`, `column_entry` |
| Schema contract | `schema_contract`, `contract_table`, `suggested_model_name`, `suggested_field_name`, `field_slug` |
| Generated code | `model_scaffold`, `admin_scaffold`, `import_scaffold` |
| View/workflow | `view_manifest`, `view_entry`, `workflow_hints`, `discovery_interview`, `discovery_summary` |
| Pipeline state | `pipeline_state`, `checkpoint`, `discovery_state`, `deep_profile_index`, `domain_knowledge`, `schema_contract`, `interaction_contract` |

### Style

- **Docstrings:** Google-style (`Args:`, `Returns:`, `Raises:`). Enforced by `interrogate` at 80%.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `ci:`).

## Human judgment points

| # | Stage | Decision needed |
|---|-------|----------------|
| 0 | Profiling | Which tabs are in scope? Which are noise? Review tab selection before Phase 3. |
| 0a | PipelineState checkpoint | Review YAML checkpoint between phases. Edit `approved_tabs` to override tab selection. Resolve alerts at each gate. See `docs/pipeline-state.md`. |
| 1 | Schema contract | Model names, field types, FK targets, computed fields, choices — all need human review. |
| 2 | Codegen review | Generated `models.py`, `admin.py`, `imports.py` must be reviewed before committing. |
| 3 | Import config | Default values, alias mappings, row filters, transform rules — human decision. |
| 4 | Import results | Row counts and error counts in summary JSON must match expectations. |
| 5 | View manifest | Editable vs computed fields, status field detection, tab sequence — human review. |
| 6 | Discovery interview | Role ownership, status semantics, weekly actions — operator fills in, human reviews merged manifest. |
| 7 | Contract breaking changes | Any field removal or type change must be explicitly approved. Use `wb drift check`. |
| 8 | Release | Verify `make chassis-gate` passes, version bumped, changelog updated. |

## Key paths

- Profiler commands: `profiler/management/commands/`
- PipelineState: `profiler/tools/pipeline_state.py`, `profiler/management/commands/run_pipeline_state.py`
- Workbook commands: `workbook/management/commands/`
- Importer base: `importer/base.py`, `importer/chassis.py`
- Connector adapters: `connectors/google_provider.py`, `connectors/coda.py`, `connectors/coda_source.py`
- Schema contract codegen: `workbook/schema_contract.py`, `workbook/field_mapping.py`
- View manifest: `workbook/view_manifest.py`, `workbook/discovery.py`
- CLI entry point: `deployment/wb_cli.py`
- Example data: `example_data/`
- Product scaffold script: `scripts/new_product.py`
- Architecture reference: `specs/tech-architecture/tech-stack.md` (generated by `map-codebase` skill)
