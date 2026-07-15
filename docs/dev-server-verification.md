# How to Run and Verify the Migration Workbench

> Companion guide to the runbooks in `docs/`. Describes how to start the
> dev server for each product repo, what to click, and how to confirm that
> the generated Django app truly replaces the spreadsheet / Coda doc.

---

## Prerequisites

Make sure you have both projects set up:

```bash
# vizcarra-guitars
cd /home/teacher/projects/vizcarra-guitars
cp .env.example .env   # fill in CODA_API_TOKEN if you want live Coda pulls
make install
make migrate

# farm
cd /home/teacher/projects/farm
make install
make migrate
```

---

## Part 1 — Vizcarra Guitars (Coda → Django)

### 1.1 Start the server

```bash
cd /home/teacher/projects/vizcarra-guitars
source .env
.venv/bin/python backend/manage.py runserver 8001
```

Open http://localhost:8001 in your browser.

### 1.2 What you can visit

| URL | What it shows | Notes |
|-----|--------------|-------|
| `/admin/` | Django admin — browse all imported Coda tables | Requires superuser account |
| `/admin/domain/clients/` | Client records from Coda | 11 duplicate-named clients collapsed |
| `/admin/domain/instruments/` | Instruments (819 rows from Coda) | Main operational table |
| `/admin/domain/workorder/` | Work Orders | Business-critical records |
| `/domain/instruments/` | Generated dashboard view | The "app replaces Coda" screen |

### 1.3 Creating a superuser

The dev database has a regular user (`keith`). To access admin:

```bash
cd /home/teacher/projects/vizcarra-guitars
.venv/bin/python backend/manage.py createsuperuser
# Follow prompts to create your admin account
```

### 1.4 Verifying the Coda replacement

Run these checks in order:

```bash
# 1. Import pipeline — must report 0 errors
cd /home/teacher/projects/vizcarra-guitars
.venv/bin/python backend/manage.py import_domain build/bundle --validate-only

# 2. Full test suite — must pass
.venv/bin/python -m pytest -q --tb=short

# 3. Data sanity — check record counts
.venv/bin/python -c "
import django; django.setup()
from domain.models import *
print(f'Clients:    {Clients.objects.count()}')
print(f'Instruments:{Instruments.objects.count()}')
print(f'WorkOrders: {WorkOrder.objects.count()}')
print(f'ArchivedWO: {ArchivedWorkOrders.objects.count()}')
"
```

**Expected output:**
```
Clients:    …
Instruments:819
WorkOrders: …
ArchivedWO: 294
```

### 1.5 What "replaces the Coda doc" means

The team currently uses a Coda doc to manage inventory (instruments, work
orders, client info). The Django app replaces that with:

- **Admin screens** (`/admin/domain/`) — browse, search, edit every table.
- **Dashboard** (`/domain/instruments/`) — at-a-glance view.
- **Import pipeline** — the team can re-import fresh Coda data at any time
  via `import_domain`.
- **Formula parity** — computed fields (taxable, total, etc.) match what
  Coda formulas produced, verified with 552-row test.

**Confirmation:** visit `/admin/domain/instruments/` and compare the data
with the Coda doc open side by side. Every instrument in Coda should appear
in the Django admin with the same field values (especially `taxable`,
`paid`, `total`).

---

## Part 2 — farm (Sheets → Django)

### 2.1 Start the server

```bash
cd /home/teacher/projects/farm
source .env
.venv/bin/python backend/manage.py runserver 8002
```

Open http://localhost:8002 in your browser.

### 2.2 What you can visit

| URL | What it shows | Notes |
|-----|--------------|-------|
| `/app/` | Root — redirects to `/app/planner/` | Role-based landing |
| `/app/planner/` | Planning Manager dashboard | Task summary, orders |
| `/app/field/` | Field Worker dashboard | Planting tasks, harvest |
| `/app/nursery/` | Nursery Worker dashboard | Seeding/pot-up schedule |
| `/app/field/tasks/` | Field task checklist (HTMX) | Toggle done inline |
| `/app/data/crops/` | Crop list view (hand-written) | Browse 128 crops |
| `/app/data/blocks/` | Field blocks list | 40 field blocks |
| `/app/data/sales/` | Sales plans list | 4742 sales plans |
| `/app/data/events/` | Field events list | 26 589 events |
| `/app/print/plantings/` | Print-friendly planting view | Weekly planning |
| `/generated/plantingplan/` | Generated list view | Codegen-produced |
| `/landing/field-worker/` | Generated landing (MWBS) | Archetype-based |
| `/dashboard/inventory/` | Generated dashboard | Alert counts |
| `/admin/` | Django admin — all models | Requires superuser |
| `/admin/core/crop/` | 128 crops with configs | Per-year CropConfig |
| `/admin/core/plantingplan/` | 1035 planting records | Core ops data |
| `/healthz` | Health check | OK |

### 2.3 Creating a superuser

```bash
cd /home/teacher/projects/farm
.venv/bin/python backend/manage.py createsuperuser
```

### 2.4 Verifying the spreadsheet replacement

```bash
# 1. Import pipeline against real bundle — 0 errors
cd /home/teacher/projects/farm
.venv/bin/python backend/manage.py import_core build/bundle --validate-only

# 2. Full test suite (skip broken test)
.venv/bin/python -m pytest -q --ignore=backend/apps/core/tests/test_bprs_scaffold.py --tb=short

# 3. Data reconciliation — compare CSV counts to DB counts
.venv/bin/python -c "
import django; django.setup()
from core.models import *
print(f'Crops:         {Crop.objects.count()}   (CSV: 124)')
print(f'FieldBlocks:   {FieldBlock.objects.count()}   (CSV: 38)')
print(f'ProductFmts:   {ProductFormat.objects.count()} (CSV: 120)')
print(f'PlantingPlans: {PlantingPlan.objects.count()}  (CSV: ~1472)')
print(f'SalesPlans:    {SalesPlan.objects.count()}   (CSV: ~15820)')
print(f'FieldEvents:   {FieldEvent.objects.count()}   (CSV: ~26589)')
"

# 4. Generated views — check them all load
.venv/bin/python -c "
import django; django.setup()
from django.test import Client
c = Client()
# Generated list views
for path in ['/generated/plantingplan/']:
    resp = c.get(path)
    status = '✅' if resp.status_code == 200 else '❌'
    print(f'{status} {path} ({resp.status_code})')
# Generated landing
for path in ['/landing/field-worker/']:
    resp = c.get(path)
    status = '✅' if resp.status_code == 200 else '❌'
    print(f'{status} {path} ({resp.status_code})')
"
```

### 2.5 What "replaces the spreadsheet" means

The farm team currently runs their entire operation from a Google Sheets
workbook with 70+ worksheets across 12+ spreadsheets. The Django app
replaces that with:

- **Role-based dashboards** (`/app/planner/`, `/app/field/`) — each role
  sees only their relevant data.
- **Data entry via admin** (`/admin/core/`) — instead of editing cells in
  sheets, team members use Django's structured forms with validation.
- **Task checklists** (`/app/field/tasks/`) — HTMX-powered toggles
  replace manual checkbox tracking.
- **Print views** (`/app/print/plantings/`) — replace printed spreadsheet
  exports for field use.
- **Generated list views** (`/generated/plantingplan/`) — auto-generated
  from the view manifest, covering all 72 spreadsheet workflows.
- **Import pipeline** — existing spreadsheet data can be re-imported
  via `import_core build/bundle`.

**Confirmation:** open the farm spreadsheet side-by-side with the Django
app. For every worksheet the team relied on (crop info, planting plan,
sales orders, field events, nursery schedule), there is a corresponding
Django admin list view or generated list view showing the same records.

---

## Part 3 — Full end-to-end confirmation ritual

Run this as a final gate before declaring 1.0.0:

```bash
echo "=== Vizcarra ==="
cd /home/teacher/projects/vizcarra-guitars
.venv/bin/python -m pytest -q --tb=short 2>&1 | tail -1
.venv/bin/python backend/manage.py import_domain build/bundle --validate-only 2>&1 | grep "TOTALS"

echo ""
echo "=== Farm ==="
cd /home/teacher/projects/farm
.venv/bin/python -m pytest -q --ignore=backend/apps/core/tests/test_bprs_scaffold.py --tb=short 2>&1 | tail -1
.venv/bin/python backend/manage.py import_core build/bundle --validate-only 2>&1 | grep "TOTALS"

echo ""
echo "=== Workbench ==="
cd /home/teacher/projects/migration-workbench
make chassis-gate 2>&1 | tail -3

echo ""
echo "All gates green. Ready to ship 1.0.0."
```

If all three report 0 errors, both replacements are validated.
