# Agent notes

## Repo identity

This is **migration-workbench** — a Python package (PyPI: `migration-workbench`) providing five Django apps (connectors, profiler, importer, workbook, deployment) that scaffolded product repos install as a dependency. The root `manage.py` and `migration_workbench/settings.py` are for development and CI. Product repos bring their own.

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

## Development workflow

```bash
make install         # venv + dev dependencies
make chassis-gate    # the full CI gate: migrate, test, lint, smoke commands
```

`make chassis-gate` is the authoritative gate. PRs must pass it. See `docs/contributing.md` for individual test commands.

## Ecosystem

This repo participates in a multi-repo development ecosystem with upstream/downstream product repos (farm, etc.). Three agent types coordinate through a filesystem-based protocol defined in `.omo/design/ecosystem.md`:

- **Meta agent** — orchestrates from this checkout. Merges worktree features to `exercise`, signals product repos, proposes squashes to human.
- **Workbench agent** — builds features in isolated worktrees, signals completion via `.omo/ready/`. Never merges.
- **Product agent** — drives quality by running the "app replaces spreadsheet" smoke test suite against generated code. Writes structured issues to `.omo/issues/` when errors are found. Certifies milestone readiness via `.omo/quality-gates/`.

See `.omo/design/ecosystem.md` for: branch model, queue protocol (7 queues), farm-led hardening loop, agent launch prompts, worktree commit rules, and patching boundary.

## Five apps

| App | Responsibility | Entry points |
|-----|---------------|--------------|
| connectors | Provider adapters (Google Sheets, Coda) | `connectors/base.py`, `connectors/router.py` |
| profiler | Read-only source inspection, PipelineState | `profiler/tools/pipeline_state.py`, `profiler/management/commands/run_pipeline_state.py` |
| importer | `BaseImportCommand` chassis, preflight/apply | `importer/base.py`, `importer/chassis.py` |
| workbook | Schema contract, codegen, view manifest | Management commands under `workbook/management/commands/` |
| deployment | Manifest validation, `wb` CLI, release store | `deployment/wb_cli.py`, `deployment/manifest.py` |

Each app has a `README.md` and a `tests/` directory. Read those before modifying.

## Testing discipline

- Write tests alongside the code in the app's `tests/` directory.
- Run the full gate before PRs: `make chassis-gate`
- Run a single test: `.venv/bin/python -m pytest profiler/tests/test_profile_commands.py::test_name`
- Doctest coverage enforced at 80%: `make doc-coverage`

## Naming & style

- **Docstrings:** Google-style (`Args:`, `Returns:`, `Raises:`). Enforced by `interrogate` at 80%.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `ci:`).
- **Versioning:** Semver. Breaking changes allowed on `0.x`; pin ranges in product repos.
- **Schema versions:** Internal checkpoint/model schema versions (e.g. `PipelineState.version`) are independent of the package version in `pyproject.toml`. A schema version bump signals a format change requiring migration; a package version bump signals a release. Never conflate the two.
- **Changelog:** Updated at the bottom of `README.md`.

## Solo release hygiene

This repo is maintained by one operator with agent assistance. The rules are
deliberately minimal — just enough to prevent the common failure modes.

**Squash before merge.** When an agent branch is ready, squash its commits into
one meaningful commit before landing on `master`. The commit message tells a
story, not a transcript of agent turns. Two workflows:

```bash
# Option A: merge --squash (simple, one command)
git checkout master
git merge --squash feature-branch
git commit -m "feat(profiler): mature PipelineState with validation, config routing, DecisionRecord"

# Option B: interactive rebase (more control)
git checkout feature-branch
git rebase -i master
# squash fixup! and chore: into feat: commits, reword messages
git checkout master
git merge feature-branch --no-ff
```

The result on `master` reads like a changelog, not a chat log:

```
v0.1.0      feat(profiler): mature PipelineState with validation, config routing, DecisionRecord
v0.0.9      feat(profiler): add PipelineState checkpoint model and Makefile scaffold
v0.9.3      fix: model_name in build_contract, wb generate in Makefile targets, Fly.io deploy configs
```

**Merge = release.** Every merge to `master` that changes user-facing behavior
gets a tag and a PyPI release. No long-lived branches. If it passes
`make chassis-gate`, it ships.

**Two versions, never one.** `pyproject.toml` version is the package release.
`PipelineState.version` is the checkpoint schema. They move independently.

**Release in three commands:**
```bash
# 1. Bump version in pyproject.toml and add ### x.y.z to README.md changelog
# 2. Commit and tag
git commit -am "release: 0.1.0"
git tag -a v0.1.0 -m "release: 0.1.0"
git push origin master && git push origin v0.1.0
```

**Pre-releases for risky changes.** If a feature branch needs testing in a
product repo before you commit to a stable release, tag it `v0.1.0a1`. Product
repos pin exactly (`==0.1.0a1`) to opt in.

**Agents do not commit on `master` or `exercise`.** On worktree branches only, agents may commit with conventional commit messages as checkpoints (see Ecosystem section above). Agents must not push, tag, merge, or rebase. Each commit captures a working state. When an agent finishes work, it shows the diff and proposes a squash commit message — you write the merge to `master`.

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

## Patching boundary

This repo is upstream. Product repos (farm, vizcarra-guitars, etc.) consume it via PyPI. When a product repo finds a gap or bug:

| Situation | Where to fix |
|-----------|-------------|
| Bug in a workbench command, template, or utility | **Here** |
| Missing feature another product would also need | **Here** |
| Column type inference misfire | **Here** |
| Import transform pipeline missing a hook point | **Here** |
| Codegen output malformed or incomplete | **Here** |
| Product-specific display logic or admin config | **Product repo** |
| Product-specific data validation or business rules | **Product repo** |
| One-off import transform for a unique source quirk | **Product repo** |

Never vendor workbench code into a product repo. Fix upstream, release to PyPI, bump the version pin.

### Workflow

1. Fix here, in the workbench checkout.
2. Run `make chassis-gate` — must pass before PR.
3. Open PR at https://github.com/anomalyco/migration-workbench.
4. After release, bump the lower bound in the product repo's `pyproject.toml`.

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