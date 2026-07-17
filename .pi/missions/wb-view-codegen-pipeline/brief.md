# brief: wb-view-codegen-pipeline

## Context
Track B (UI codegen extraction). Three archetypes now exist in
`workbook/codegen/view_generator.py` — checklist (0.6.1), landing (0.6.3),
and dashboard (0.7.2) — each proven against real farm data. Each archetype
is invoked through the `generate_views` Django management command.

What's missing: there is no `wb generate views` CLI command (the `wb` CLI
already has `generate models`, `generate admin`, `generate import`, and
`generate manifest`), and the `generate-all` Makefile target does not include
view generation. Product repos that want generated views must run the
management command directly.

Additionally, the generated templates lack a formal product-skin override
mechanism. Each archetype has its own `base_template` handling (dashboard
supports it in config; checklist and landing hardcode `"base.html"`). There
are no `{% block %}` override points in the generated templates, so product
repos cannot customize generated views without editing the output files —
defeating the purpose of generation.

This mission closes the pipeline gap: a product repo runs `make generate-all`
and gets views alongside models, admin, and imports. The views use a template
package mechanism so product repos can supply custom base templates and
override blocks without touching generated output.

## Goal
Add `wb generate views` to the CLI, wire it into `generate-all`, and add a
template package / product-skin override system so generated views use
product-provided base templates and template blocks.

## Repo
migration-workbench (primary) + farm (test target)

## Starting State
- `deployment/wb_cli.py` has `wb generate {models,admin,import,manifest}` but
  not `wb generate views`
- `workbook/makefile_targets.py::generate_all_block()` lists:
  `generate-models generate-view-manifest merge-interaction-contract
   generate-admin generate-import generate-pipeline-manifest`
  — no `generate-views`
- Main `Makefile` `generate-all` target mirrors the above
- `ChecklistArchetype` and `LandingArchetype` hardcode `"base.html"` as the
  template extends target; `DashboardArchetype` supports `base_template`
- Generated templates have no `{% block %}` override points
- 1720 tests pass; `make chassis-gate` green

## Scope

### In-scope

#### 1. `wb generate views` CLI command
Add `_generate_views()` handler and `views` subcommand parser in
`deployment/wb_cli.py::_build_generate_parser()`, mirroring the pattern used
by `_generate_models`/`_generate_admin`/`_generate_import`. Arguments:
- `--contract` (required) — schema-contract YAML path
- `--out-dir` (required) — output directory for generated views/templates
- `--app-label` — Django app label (default: from contract or "core")
- `--archetype-checklist` — checklist target ("auto" or AppLabel.ModelName list)
- `--archetype-landing` — landing config YAML path
- `--archetype-dashboard` — dashboard config YAML path
- `--template-package` — path to product-skin override templates directory
- `--force` — overwrite existing files
- `--validate` — strict-validate contract before rendering

#### 2. Template package / product-skin override blocks
Add a general template override mechanism:
- Add `base_template` field to `ChecklistArchetype` and `LandingArchetype`
  (default `"base.html"`) — already exists on `DashboardArchetype`
- Add `{% block %}` override points to all generated templates:
  - `{% block title %}` — page title
  - `{% block content %}` — main content area (wraps the existing body)
  - Archetype-specific blocks: `{% block alert_cards %}`, `{% block detail_sections %}`,
    `{% block checklist_table %}`, `{% block summary_cards %}`, etc.
- The `--template-package` flag accepts a directory path. When provided,
  generated views pass it as a template search path so product templates
  override workbench defaults. (Django's template loading handles the search
  chain; the mechanism is documented in the generated Makefile.)

#### 3. Wire into `generate-all`
- Add `generate-views:` target to `workbook/makefile_targets.py`:
  a `generate_views_block()` function and a `generate_views()` target spec
  using `--contract`, `--out-dir`, `--template-package` from the MakeContext
- Add `generate-views` to the `generate-all` dependency list
- Add `generate-views` to the phonies list
- Update the main `Makefile` `generate-all` target to include `generate-views`

#### 4. Tests
- Unit tests for `_generate_views` in `wb_cli` (argument forwarding,
  template-package flag)
- Unit test for `generate_views_block()` in `makefile_targets.py`
- Update `test_generate_all_block_includes_pipeline_manifest` to also check
  for `generate-views`
- Unit tests for `base_template` on ChecklistArchetype and LandingArchetype
- Unit tests for `--template-package` flag parsing and template override path
- Farm real-data test: generate views with a product-skin override template,
  verify the override renders instead of the default

### Known risks
- **Farm real-data test may surface integration bugs** (template override resolution,
  URL import paths, generated view rendering) that don't fit neatly into the 0.7.3
  patch. Any such bug is absorbed into this mission or triaged to a separate patch
  — it does not block the pipeline wiring.
- The working tree may already contain partial implementation toward this brief
  from a prior session. Verify `git status` before duplicating work.

### Out-of-scope
- Consuming MWBS `Report` objects directly (that's 0.8.1 `vizcarra-generated-ui`)
- Per-archetype module name support (separate `views_checklist_auto.py` etc. —
  noted as a follow-up)
- Adding new archetypes (the pipeline mission wires existing ones into the CLI)
- Coverage/drift report command (future extraction backlog)
- Print-friendly weekly summary view (future extraction backlog)

## Success Criteria
- [ ] `wb generate views --contract ... --out-dir ... --archetype-checklist auto`
      generates valid Python + templates (same output as `manage.py generate_views`)
- [ ] `wb generate views --archetype-landing ... --template-package <dir>` uses
      product-provided base templates
- [ ] Generated templates have `{% block %}` override points (title, content,
      archetype-specific blocks)
- [ ] `base_template` configurable on all three archetypes
- [ ] `make generate-views` target works (via Makefile or shared targets)
- [ ] `make generate-all` includes `generate-views`
- [ ] Workbench unit tests pass (ast-validated views, template structure,
      CLI argument forwarding, Makefile target, base_template defaults)
- [ ] Farm real-data test proves template override works against real data
- [ ] `make chassis-gate` passes
- [ ] Squash-merge to master, tag v0.7.3

## Earns
0.7.3 — View codegen pipeline: `wb generate views` command wired into
`generate-all`, with template package and product-skin override blocks.
Proven against real farm data.
