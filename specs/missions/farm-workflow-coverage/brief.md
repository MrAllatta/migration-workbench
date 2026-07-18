# brief: farm-workflow-coverage (Track B, 0.8.6)

## Context

The farm project has 72 view-manifest entries mapping spreadsheet tabs to
Django views, but only 19 hand-written views in ``backend/apps/farm_ui/``.
The 0.8.5 mission built a ``ListArchetype`` + ``render_list_view_py``
generator, but it is not yet wired into the ``wb generate views`` command or
driven by the view manifest.  List views are currently generated only by
hand-crafting MWBS ``WorkflowStep`` objects in tests.

The view manifest is the authoritative map of farm's spreadsheet workflows.
Each entry has: ``name``, ``entity``, ``source_tab``, ``type``,
``filterable_by``, ``status_field``, ``time_scope``, ``editable_fields``,
and ``workflow_hints``.  This is enough information to generate a basic
list view for most workflows.

## Goal

Wire ``workbook/codegen/list_generator.py`` into ``wb generate views`` so
that the command can consume the view manifest and emit generated list
views for farm spreadsheet workflows.  Prove coverage by generating views
for all 72 manifest entries and validating that the generated code is
syntactically valid and references real models/fields from the contract.

## Starting State

- ``workbook/codegen/list_generator.py`` exists with ``ListArchetype``
  and ``render_list_view_py`` (from 0.8.5).
- ``workbook/management/commands/generate_views.py`` generates checklist,
  landing, and dashboard archetypes from the schema contract.
- Farm ``config/view-manifest.yaml`` has 72 entries; ``config/contract.yaml``
  has 21 tables.
- Farm ``backend/apps/farm_ui/`` has 19 hand-written views proving the
  desired list view pattern.

## Scope

### In-scope

1. **View manifest loader** — Add a helper in ``workbook/codegen/`` that
   reads ``view-manifest.yaml`` and returns view entries with normalized
   fields.

2. **Manifest-to-list-archetype adapter** — Convert a view-manifest entry
   into a ``ListArchetype`` using:
   - ``entity`` → ``model`` (via contract ``suggested_model_name`` or direct mapping)
   - ``filterable_by`` → ``filters``
   - ``source_tab`` + ``name`` → ``title``
   - contract table columns → ``columns`` (first N non-pk displayable fields)
   - sensible defaults for ``paginate_by`` (50) and ``ordering`` (name/id)

3. **Integrate with ``generate_views`` command** — Add an
   ``--archetype-list-from-manifest`` mode that:
   - Reads the contract and view manifest
   - Emits one list view per manifest entry
   - Writes ``views_auto.py``, ``urls_auto.py``, and templates

4. **Coverage report** — Generate a markdown report
   ``build/_out/workflow-coverage.md`` showing:
   - Source tab
   - View name
   - Generated view class name
   - Status (ok / missing-model / invalid-filter / skipped)

5. **Farm validation** — In the farm product repo, run the command against
   the real farm config and assert:
   - All 72 manifest entries are represented in the generated output
   - Generated ``views_auto.py`` parses as valid Python
   - At least one generated view can be imported/loaded in a Django test

### Out-of-scope

- Replacing the hand-written ``farm_ui/`` views (the generated views live
  in ``generated/`` side-by-side for now).
- Perfect fidelity to hand-written filters (e.g. selected value sidebar
  keys may differ; we validate structure, not pixel parity).
- Generating dashboards, checklists, or prints from the manifest (those
  use existing archetype modes).
- Human-edited MWBS workflows (still use the 0.8.5 adapter separately).

## Success Criteria

- [ ] View manifest loader helper exists and is unit tested
- [ ] Manifest entry → ``ListArchetype`` adapter exists and is unit tested
- [ ] ``generate_views --archetype-list-from-manifest`` generates
      list views for all 72 farm manifest entries
- [ ] Coverage report written to ``build/_out/workflow-coverage.md``
- [ ] Generated ``views_auto.py`` is valid Python (AST parse)
- [ ] Farm test confirms all 72 entries are represented
- [ ] Workbench ``make chassis-gate`` green
- [ ] Farm test suite green
- [ ] Merge to master, tag v0.8.6

## Earns

0.8.6 — All farm spreadsheet workflows mapped to generated views; the
view codegen pipeline is now manifest-driven for list views.
