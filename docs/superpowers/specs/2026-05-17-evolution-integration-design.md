# Evolution Branch Integration Design

Merge 5 worktree branches into master in dependency order, produce a coherent
`admin_generator.py` that combines FK link methods, time scoping, status
actions, and editable-fields support, then catch up the documentation branch
to reflect the new features.

## Merge Sequence

```
master (e40ecf1)
 └─ view-manifest-inference  ──► merge #1 (foundation, no conflicts)
      └─ admin-time-status   ──► merge #2 (time scoping, status actions, editable fields)
      └─ admin-formula-fk    ──► merge #3 (FK link methods; conflicts with #2)
pipeline-manifest  ──────────────► merge #4 (independent, no conflicts)
docs-coverage      ──────────────► rebase on merged master, then merge (or merge then add missing docs)
```

### Phase 1 — Merge view-manifest-inference → master

Commits: `36e90c0` (feat: infer time_scope and status_values) + `ec99e65`
(cleanup).

Changes: `workbook/view_manifest.py` (+59/-1), `test_view_manifest.py` (+135).

No conflicts with master. Straightforward fast-forward or merge commit.

### Phase 2 — Merge admin-time-status → master

Commits: `7a5941c` + `db11fbc` (already in master after Phase 1) + `e8c3a09`
(feat: time-scoping, status actions, editable fields) + `18ae3d5` (fix: safe
slugification).

Changes: `admin_generator.py` (+82), `test_admin_generator.py` (+207),
`view_manifest.py` (already in master), `test_view_manifest.py` (already in
master after Phase 1).

Manual conflict resolution needed in `admin_generator.py` — see Combined
Interface below.

### Phase 3 — Merge admin-formula-fk → master

Commits: `7a5941c` + `db11fbc` (already in master) + `60a1888` (feat: FK link
methods) + `4cfc81b` (fix: better FK link).

Changes: `admin_generator.py` (+61), `test_admin_generator.py` (+135).

Manual conflict resolution needed in `admin_generator.py` — already resolved
in Phase 2 against the combined interface.

### Phase 4 — Merge pipeline-manifest → master

Commits: `5cce30f` through `9d8c9bc` (6 commits).

Changes: `pipeline_manifest.py` (new), `generate_pipeline_manifest.py` (new),
test files (new), `Makefile` (+5 lines).

No conflicts. Also wire `generate-pipeline-manifest` into the `generate-all`
Makefile target.

### Phase 5 — Rebase docs-coverage on merged master + add docs

Rebase the 10 docs-coverage commits on top of merged master, then add missing
documentation for the evolution features (view manifest reference, pipeline
manifest reference, updated INDEX, updated tutorial — see Phase 6 below).

### Phase 6 — Documentation catch-up

In the docs-coverage branch (after rebase), add or update:

- `docs/view-manifest.md` — reference doc for the view-manifest-draft-1 format
  covering `version`, `status_field`, `status_values`, `time_scope`
  (`year_field`, `week_field`, `date_field`, `default_scope`),
  `editable_fields`, `computed_fields`, `filterable_by`
- `docs/pipeline-manifest.md` — reference doc for the pipeline manifest YAML
  format
- `docs/INDEX.md` — add entries for view manifest, pipeline manifest, admin
  generation features
- `README.md` — add rows to Documentation Map table
- `docs/end-to-end-tutorial.md` — add view-manifest generation step and
  pipeline-manifest generation step

## Combined `admin_generator.py` Interface

### `_render_admin_class()` — combined signature

```python
def _render_admin_class(
    model_name: str,
    display_fields: list[str],
    filter_fields: list[str],
    search_fields: list[str],
    readonly_fields: list[str],
    list_editable_fields: list[str],
    autocomplete_fields_list: list[str],
    inline_classes: list[str],
    verbose_name: str | None,
    admin_base_class: str = "admin.ModelAdmin",
    status_field: str | None = None,
    link_methods: list[str] | None = None,
    time_scope: dict[str, Any] | None = None,
    status_values: list[str] | None = None,
    editable_fields: list[str] | None = None,
) -> str:
```

Rendering order within the function body:

1. `# status_field:` comment block (existing)
2. `@admin.register` / class header (existing)
3. Year-field injection into `filter_fields` when `time_scope` has
   `year_field` (from time-status branch)
4. `list_display = [...]` (existing)
5. FK link method code after list_display (from FK branch — `link_methods`
   rendered as bare methods inside the class body)
6. `list_filter`, `search_fields`, `list_editable`, `readonly_fields`,
   `autocomplete_fields`, `inlines` (existing)
7. `date_hierarchy = '...'` when `time_scope` has `date_field` (from
   time-status branch)
8. `fields = [...]` from `editable_fields` (from time-status branch)
9. `get_queryset()` override when `time_scope` has `year_field` (from
   time-status branch)
10. `@admin.action` methods from `status_values` + `status_field` (from
    time-status branch)
11. `pass` guard — also check `date_hierarchy`, `get_queryset`, status
    actions, and `fields` from editable_fields before emitting `pass`
    (from time-status branch, adapted)

### `_render_imports()` — combined

```python
def _render_imports(
    tables: list[dict[str, Any]],
    *,
    needs_user_admin: bool,
    needs_fk_links: bool = False,
    needs_timezone: bool = False,
) -> str:
```

Import block emitted in this order:

1. `from django.contrib import admin`
2. If `needs_fk_links`: `from django.urls import reverse`, `from
   django.utils.html import format_html`
3. If `needs_user_admin`: `from django.contrib.auth.admin import UserAdmin
   as BaseUserAdmin`
4. If `needs_timezone`: `from django.utils import timezone`
5. `from .models import ...`

### `render_admin_py()` — combined logic

Pre-scan phase:

1. `needs_user_admin` — scan for `AbstractUser` models (existing)
2. `needs_fk_links` — scan contract tables for FK fields that are not
   `"self"` (from FK branch)
3. `needs_timezone` — scan manifest for views with `time_scope.year_field`
   (from time-status branch)

Per-table loop collects:

- `status_field` (existing)
- `link_methods` — generated for each FK field that appears in `list_display`
  (from FK branch)
- `time_scope`, `status_values`, `editable_fields` — read from view manifest
  entry (from time-status branch)

All passed to `_render_admin_class()`.

## Testing

After each phase, run the full test suite:

- Phase 1: `view_manifest` tests pass (11 tests)
- Phase 2: all tests pass (existing + new admin/time-status tests)
- Phase 3: all tests pass (existing + new FK link tests)
- Phase 4: all tests pass (existing + new pipeline manifest tests)
- Phase 5-6: interrogate 80% threshold passes, all docs render correctly

## Non-goals

- No refactoring of `admin_generator.py` beyond what's needed to resolve the
  merge conflicts.
- No new features beyond what the evolution branches already implement.
- Existing documentation that correctly describes pre-evolution behavior is
  left as-is.
