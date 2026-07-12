# journal: vizcarra-generated-ui

Track B 0.8.1 — Consume the `wb generate views` pipeline on vizcarra-guitars,
regenerating existing views and adding archetype-generated UI. Proves the
codegen pipeline generalises beyond the source engagement (farm).

## Status
Booted.

## Branch
`feat/vizcarra-generated-ui`

## Log

### 2026-07-12 — Boot
- Created from the portfolio Next table after `wb-view-codegen-pipeline` (0.7.3).
- Brief written: template package, regenerate landing view, add checklist/dashboard
  archetype views, real-data tests in vizcarra-guitars.
- Prerequisites: upgrade vizcarra-guitars workbench dependency, create template package.

### 2026-07-12 — Boot complete
- `make hygiene` clean on migration-workbench.
- Portfolio updated: `vizcarra-generated-ui` marked Active.
- Feature branch `feat/vizcarra-generated-ui` created from master at `b82c354`.

### 2026-07-12 — Implementation

**vizcarra-guitars:**
- Upgraded migration-workbench from 0.6.1 to 0.7.3 (editable from local checkout)
- Created `backend/templates/base.html` extending `admin/base.html` with Vizcarra brand tokens
- Added `backend/templates` to TEMPLATES.DIRS in settings.py
- Created landing config at `backend/apps/domain/config/landing-config.yaml`
- Regenerated landing view via `wb generate views --archetype-landing` (extends base.html)
- Created dashboard config for Instruments inventory (In Shop, For Sale, Total alerts + detail table)
- Generated dashboard to separate `views_dashboard_auto.py`/`urls_dashboard_auto.py`
- Created `domain/urls.py` aggregator that includes both `urls_auto` and `urls_dashboard_auto`
- Updated `config/urls.py` to include `domain.urls` instead of `domain.urls_auto`
- Added `generate-views`, `generate-all`, and `test` Makefile targets
- 5 new dashboard tests: login gate, title, alerts, detail table with seeded Instrument, empty state
- All 30 domain tests pass

**Migration-workbench:**
- Bumped pyproject.toml to 0.8.1
- Updated README.md changelog with 0.8.1 entry
- Updated docs/roadmap.md with joint cut-over model (Track B farm missions post-Vizcarra)
- Updated portfolio with Track A/B mission sequence
- `make chassis-gate`: 1783 passed, 1 warning (green)

**State:**
- Workbench: feat/vizcarra-generated-ui (1 uncommitted code change — version bump + changelog)
- Vizcarra-guitars: feat/vizcarra-generated-ui (1 commit, 14 files, 280 lines added)
- Vizcarra-guitars: 30 domain tests pass
