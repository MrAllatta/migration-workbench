# journal: vizcarra-people-type

Track A 0.8.2 — Map Coda People columns to Django users in vizcarra-guitars.

## Status
Planned.

## Branch
`feat/vizcarra-people-type`

## Log

### 2026-07-12 — Designed
- Brief written: workbench profiler enrichment for People columns, user mapping
  in vizcarra-guitars, real-data import tests.
- Precondition: complete after `vizcarra-generated-ui` (0.8.1).

### 2026-07-12 — Booted
- `master` chassis-gate: 1743 passed, exit code 0.
- Worktree `../migration-workbench-vizcarra-people-type` created on branch `feat/vizcarra-people-type`.
- Portfolio marked Active: `vizcarra-people-type` (Track A, 0.8.2).

### 2026-07-12 — Workbench side done (vertical slices)

Three TDD cycles completed on the workbench:

1. **extract_relation_columns** — person columns now emit `is_user_reference=True`
   and `target_table_name='auth.User'` instead of the old unresolved note.
2. **build_contract** — the relation_columns enrichment loop handles person
   columns, upgrading them to `ForeignKey(to='auth.User')`.
3. **render_field** — verified that `'auth.User'` renders correctly as a
   quoted string FK target (no code change needed).

1746 workbench tests pass. Chassis-gate green.

### 2026-07-12 — Vizcarra side done (product repo)

Four commits on `feat/vizcarra-people-type` (vizcarra-guitars):

1. **User mapping utility** — `domain/user_mapping.py`: `parse_coda_person_value`,
   `resolve_coda_person_to_user`, `get_or_create_coda_user`. 21 unit tests.
2. **Model change** — `created_by` changed from TextField to
   `ForeignKey(auth.User)` on Clients and Instruments (migration 0002).
3. **Import hook update** — `_prepare_created_by` uses `get_or_create_coda_user`
   to resolve Coda person JSON-LD to Django User.
4. **Tests** — `TestPrepareCreatedByHook`: 4 tests covering existing user
   resolution, on-demand creation, unparseable handling, idempotency.

55 domain tests pass.

### Decision: Instruments.owner

The `Instruments.owner` column is a Coda `lookup` to the `Clients` table,
not a person reference. It correctly stays as `ForeignKey(Clients)` and
is not affected by this mission. Documented in the brief.

### 2026-07-12 — Released

- Squash-merged to master on both repos.
- Tagged v0.8.2 on workbench.
- Feature branches deleted.
- 11 remaining `unique_on: [first]` errors deferred to `vizcarra-import-pipeline` (0.8.4).
