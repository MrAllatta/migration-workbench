# brief: vizcarra-people-type (Track A, 0.8.2)

## Context
Vizcarra's Coda doc uses **People** columns for ownership and auditing:
`Created By`, `Owner`, assignees on work orders, etc. In the current
migration these columns are scaffolded as `TextField` (e.g.
`created_by = models.TextField(blank=True)`) or as FKs to other domain
models. They are **not** linked to Django users, so the generated app
cannot answer "show me my work orders" or enforce per-user access.

For the team to use the Django app day-to-day (1.0.0), Coda people must
resolve to Django `User` records. This requires two things:

1. **Workbench enrichment** — the Coda profiler must detect People columns
   and scaffold `ForeignKey(User)` or `ManyToManyField(User)` instead of
   `TextField`.
2. **Product mapping** — the Vizcarra product repo must map Coda person
   identities (name/email) to Django users and regenerate the domain models.

This mission is the first Coda-side validation after `vizcarra-views-deploy`
(0.7.1) and closes the user-identity gap before cutover.

## Goal
Map Coda People columns to Django users in vizcarra-guitars: enrich the
workbench profiler, regenerate the schema contract and models, and prove that
ownership and audit fields resolve to real Django `User` records when
importing from Coda.

## Repo
migration-workbench (profiler enrichment) + vizcarra-guitars (mapping + tests)

## Starting State
- Coda profiler detects `lookup`, `text`, `date`, `number`, `checkbox`, etc.
- `created_by` is a `TextField` on `WorkOrders` and `ArchivedWorkOrders`.
- `Instruments.owner` is a `ForeignKey('Clients')`, not a Django user.
- vizcarra-guitars has Django admin users (`admin_user` fixture) but no
  mapping from Coda people.
- Workbench: `make chassis-gate` green.

## Scope

### In-scope
1. **Workbench: detect People columns**
   - Update Coda column profiler to recognise Coda's `people` / `person`
     column type (or the metadata shape that represents it).
   - Emit `data_type: ForeignKey` (or `ManyToManyField` for multi-select
     people) targeting `auth.User` in the schema contract.
   - Add a unit test with a sample Coda column profile.

2. **Workbench: user FK scaffolding**
   - Ensure `model_generator.py` renders `models.ForeignKey(settings.AUTH_USER_MODEL,
     ...)` or `models.ManyToManyField(settings.AUTH_USER_MODEL, ...)` for
     people columns.
   - Ensure import generator can receive a user-mapping hook.

3. **vizcarra-guitars: user mapping**
   - Build a `coda_person_to_user` map (name/email → Django `User`).
   - Extend `import_domain.py` to resolve `created_by`, `owner`, etc. through
     the map.
   - Add a management command or fixture to create missing Django users from
     the Coda people list.

4. **Regenerate artifacts**
   - Re-profile the Coda doc, regenerate schema contracts, models, admin,
     import command.
   - Run migrations.

5. **Real-data tests**
   - Import a subset of real Coda records.
   - Assert `created_by` resolves to a Django `User` instance (not text).
   - Assert `Instruments.owner` resolves to a `User` (or stays as `Clients`
     if business rule requires; document decision).

### Out-of-scope
- Full Coda user sync automation (one-shot seeding is enough for this gate).
- Role-based permissions beyond simple user identity.
- Replacing Coda sharing model.

## Success Criteria
- [ ] Workbench profiler unit test: People column → `ForeignKey(User)`
- [ ] Generated model uses `settings.AUTH_USER_MODEL` for people columns
- [ ] vizcarra-guitars user-mapping exists and is exercised during import
- [ ] Real Coda import creates/updates Django `User` records
- [ ] Imported records have `created_by` / owner FKs populated
- [ ] Workbench `make chassis-gate` green
- [ ] vizcarra-guitars tests pass
- [ ] Merge to master, tag v0.8.2

## Earns
0.8.2 — Coda People columns mapped to Django users; user identity and
ownership are correct in the generated Vizcarra app.
