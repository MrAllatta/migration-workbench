# SaaS Service Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the customer-facing contract documents and internal onboarding workflows defined in the SaaS service contract design spec.

**Architecture:** Three workstreams: (1) legal contract templates drawn from the spec's terms, (2) an internal onboarding checklist/script for the solo operator, (3) a lightweight scoping assessment tool that profiles spreadsheet complexity. These are standalone deliverables, not a running system.

**Tech Stack:** Markdown templates, Python (existing profiler infrastructure), Jinja2 for template rendering.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `contracts/service-contract-template.md` | Master service contract — all terms from the spec rendered as a fill-in-the-blank template |
| `contracts/dpa-addendum.md` | Data Processing Agreement addendum |
| `contracts/scoping-sow-template.md` | Scoping SOW — fixed-fee engagement for complexity assessment |
| `scripts/scoping_assessment.py` | CLI tool that runs profiler tab detection + produces a complexity summary |
| `scripts/onboarding-checklist.md` | Internal SOP for the solo operator — from discovery call through go-live |

---

### Task 1: Write the Service Contract Template

**Files:**
- Create: `contracts/service-contract-template.md`

- [ ] **Step 1: Write the service contract template**

```markdown
# Service Contract Template

> **Instructions:** Replace `[bracketed]` sections per engagement. This is a starting point — review with qualified legal counsel before use.

---

## Parties

- **Provider:** [Your Name / Company], [Address]
- **Customer:** [Customer Name], [Customer Address]

## Effective Date

[Date]

## Services

### 1. Scope

Provider will perform the following services for Customer:

**Build Phase (one-time):**
- Connect to Customer's source spreadsheets (Google Sheets / Coda)
- Profile source data (tab discovery, entity identification, relationship mapping)
- Generate schema contract YAML mapping spreadsheets to Django models
- Generate Django models, admin interface, and import commands
- Import Customer data into the generated application
- Deploy a single-tenant Django application on Fly.io (or equivalent infrastructure)

**Run Phase (monthly recurring):**
- Host the deployed application
- Maintain automated database backups (Litestream replication to S3)
- Apply security patches and dependency updates
- Monitor application health

**Evolve Phase (as needed):**
- Schema evolution, new features, additional data sources — billed separately per SOW

### 2. Customer Responsibilities

- Provide access to source spreadsheets or documents
- Review and approve the schema contract before codegen begins
- Participate in UAT (user acceptance testing) before go-live
- Notify Provider of any data breaches or security concerns involving their account

### 3. Contract Maturity Tier

This contract operates under **Tier [1/2/3]** as defined in the Service Tier Schedule attached hereto. The current tier is **Tier 1 — Deploy + UAT**. Provider will notify Customer of tier progression.

### 4. Fees & Payment

| Item | Amount | Due |
|------|--------|-----|
| Scoping Assessment (fixed fee) | $[amount] | Upon signing Scoping SOW |
| Build Phase (fixed fee or T&M) | $[amount] | [50% upon signing / 50% at go-live] |
| Run Phase (monthly) | $[amount] | Monthly in arrears |
| Evolve Phase | Per SOW | Per SOW terms |

Scoping fee credits toward Build Phase if Customer proceeds to Build.

### 5. Term & Termination

- **Initial term:** [Month-to-month / 12 months], auto-renews
- **Cancellation:** 30 days written notice
- **On termination:** Provider will deliver a GitHub repository with all generated code, a SQLite data export, CSV exports, and self-deploy instructions within 14 days. Customer data will be purged from provider systems 30 days after termination.

### 6. Data Ownership

- Customer retains full ownership of their source data and business data
- Customer receives a perpetual, unrestricted license to all generated code
- Provider retains ownership of the migration-workbench platform

### 7. Limitation of Liability

[Standard limitation — recommend legal review]

### 8. Governing Law

[State/Country]

---

**Signatures:**

_________________________           Date: ______________
Provider

_________________________           Date: ______________
Customer
```

- [ ] **Step 2: Commit**

```bash
git add contracts/service-contract-template.md
git commit -m "feat: add service contract template"
```

---

### Task 2: Write the DPA Addendum

**Files:**
- Create: `contracts/dpa-addendum.md`

- [ ] **Step 1: Write the DPA addendum**

```markdown
# Data Processing Agreement (DPA) Addendum

This DPA forms part of the Service Contract between [Provider] and [Customer].

## 1. Data Processing

### 1.1 Nature and Purpose
Provider processes Customer data solely to deliver the Services described in the Service Contract: hosting a Django application, maintaining backups, and supporting the application.

### 1.2 Categories of Data
Customer's source spreadsheet data and any data entered into the generated Django application.

### 1.3 Data Subjects
Customer's employees, contractors, and business contacts as reflected in Customer's spreadsheets.

## 2. Sub-processors

Customer authorizes the following sub-processors:

| Sub-processor | Service | Location |
|---------------|---------|----------|
| Fly.io | Application hosting | US (ewr) |
| Tigris / AWS S3 | Backup storage | US |
| GitHub | Code repository delivery | US |

Provider will notify Customer 30 days before adding or replacing any sub-processor.

## 3. Data Security

Provider maintains the following security measures:
- Encryption in transit (TLS) for all application traffic
- Database backups replicated to S3 with 14-day retention
- Single-tenant infrastructure (Customer's data is not co-mingled)

## 4. Breach Notification

Provider will notify Customer within 72 hours of discovering a data breach affecting Customer data.

## 5. Data Retention & Deletion

- Customer data is retained for the duration of the Service Contract plus 30 days
- Upon Customer's request or 30 days post-termination, Provider will delete all Customer data from production and backup systems
- Provider will provide a full data export to Customer before deletion

## 6. Governing Law

Same as Service Contract.

---

**Signatures:**

_________________________           Date: ______________
Provider

_________________________           Date: ______________
Customer
```

- [ ] **Step 2: Commit**

```bash
git add contracts/dpa-addendum.md
git commit -m "feat: add DPA addendum template"
```

---

### Task 3: Write the Scoping SOW Template

**Files:**
- Create: `contracts/scoping-sow-template.md`

- [ ] **Step 1: Write the scoping SOW template**

```markdown
# Scoping Statement of Work

## Engagement

Provider will perform a fixed-fee scoping assessment for Customer.

## Deliverable

A written assessment including:
- Spreadsheet inventory (tabs, columns, row counts)
- Complexity analysis (formula density, cross-sheet references, data validation rules)
- Entity and relationship discovery
- Estimated Build Phase cost range and timeline
- Recommendations for Appliance vs Partnership engagement model

## Fee

Fixed fee: $[amount]. Credits toward Build Phase if Customer proceeds.

## Timeline

[1-2 weeks from signed SOW and source access]

## Source Access

Customer grants Provider read access to the following:
- [Google Drive folder / Coda workspace URL]
- Any additional documentation about business workflows

---

**Signatures:**

_________________________           Date: ______________
Provider

_________________________           Date: ______________
Customer
```

- [ ] **Step 2: Commit**

```bash
git add contracts/scoping-sow-template.md
git commit -m "feat: add scoping SOW template"
```

---

### Task 4: Write Internal Onboarding Checklist

**Files:**
- Create: `scripts/onboarding-checklist.md`

- [ ] **Step 1: Write the onboarding SOP**

```markdown
# Onboarding SOP

> **For the solo operator.** Follow this sequence for each new customer engagement.

## Phase 0: Discovery

- [ ] Schedule 30min discovery call
- [ ] Understand: business model, spreadsheet workflow, user count, pain points
- [ ] Determine fit: is this a Partnership or Appliance engagement?
- [ ] If fit: ask for source access (read-only is sufficient)

## Phase 1: Scoping

- [ ] Configure auth for source (Google Sheets / Coda)
- [ ] Run `python scripts/scoping_assessment.py --source <url>` to produce automated assessment
- [ ] Review assessment output manually
- [ ] Prepare scoping SOW with fee estimate
- [ ] Send scoping SOW for signature
- [ ] Receive signed SOW + payment

## Phase 2: Scoping Delivery

- [ ] Profile spreadsheets (run full profiler pipeline)
- [ ] Produce complexity assessment document
- [ ] Estimate Build Phase cost and timeline
- [ ] Present to customer in a review call
- [ ] If proceeding: credit scoping fee, prepare Build contract + DPA

## Phase 3: Build

- [ ] Sign Build contract + DPA
- [ ] Run full pipeline: profile → contract → generate → import
- [ ] **Critical: schema contract review** — present to customer, get written approval
- [ ] Generate models, admin, import
- [ ] Import data, validate row counts
- [ ] Deploy to Fly.io
- [ ] Configure custom domain (if applicable)
- [ ] Verify `/healthz` passes

## Phase 4: UAT

- [ ] Walk customer through the admin interface
- [ ] Customer tests against their spreadsheets for 1-2 weeks
- [ ] Log and fix any issues found
- [ ] Customer signs off on UAT

## Phase 5: Go-Live

- [ ] Set up monthly billing
- [ ] Hand over GitHub repo access
- [ ] Send welcome package: app URL, admin credentials, support contact
- [ ] Schedule first quarterly check-in
- [ ] Move to Tier 1 run phase

## Quarterly Check-In

- [ ] Has the business changed? New spreadsheets? New workflows?
- [ ] Are there feature requests?
- [ ] Review app health (uptime, error logs, backup status)
- [ ] Discuss tier progression if applicable
```

- [ ] **Step 2: Commit**

```bash
git add scripts/onboarding-checklist.md
git commit -m "docs: add onboarding SOP checklist"
```

---

### Task 5: Scoping Assessment CLI Tool

**Files:**
- Create: `scripts/scoping_assessment.py`
- Test: `scripts/tests/test_scoping_assessment.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for scoping_assessment.py."""
import json
from pathlib import Path
from scripts.scoping_assessment import assess_spreadsheet_complexity

SAMPLE_PROFILE = {
    "tabs": [
        {"title": "Crop Planner", "columns": ["Crop", "Type", "Plant Date", "Block"], "row_count": 500, "formula_columns": 1},
        {"title": "Planting Log", "columns": ["Date", "Field", "Crop", "Seed Qty", "Notes"], "row_count": 1200, "formula_columns": 0},
        {"title": "Harvest Log", "columns": ["Date", "Field", "Crop", "Qty", "Grade", "Notes"], "row_count": 800, "formula_columns": 1},
    ],
    "cross_sheet_refs": [
        {"from": "Harvest Log", "to": "Crop Planner", "ref_count": 1},
    ],
}


def test_assess_spreadsheet_complexity_returns_expected_keys():
    result = assess_spreadsheet_complexity(SAMPLE_PROFILE)
    assert "tab_count" in result
    assert "total_rows" in result
    assert "formula_density" in result
    assert "cross_sheet_ref_count" in result
    assert "complexity_tier" in result
    assert "estimated_build_weeks" in result
    assert "recommendation" in result


def test_simple_spreadsheet_is_appliance():
    simple = {"tabs": [{"title": "Sheet1", "columns": ["A", "B"], "row_count": 50, "formula_columns": 0}], "cross_sheet_refs": []}
    result = assess_spreadsheet_complexity(simple)
    assert result["complexity_tier"] == "appliance"


def test_complex_spreadsheet_is_partnership():
    complex_profile = {
        "tabs": [
            {"title": f"Tab{i}", "columns": [f"Col{j}" for j in range(15)], "row_count": 2000, "formula_columns": 8}
            for i in range(12)
        ],
        "cross_sheet_refs": [
            {"from": f"Tab{i}", "to": f"Tab{j}", "ref_count": 3}
            for i in range(12) for j in range(12) if i != j
        ],
    }
    result = assess_spreadsheet_complexity(complex_profile)
    assert result["complexity_tier"] == "partnership"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest scripts/tests/test_scoping_assessment.py -v`
Expected: FAIL with "ModuleNotFoundError" or similar

- [ ] **Step 3: Write the scoping assessment script**

```python
"""CLI tool that profiles spreadsheet complexity and produces a scoping estimate.

Usage:
    python scripts/scoping_assessment.py --profile profiler_output.json
    python scripts/scoping_assessment.py --source "https://sheets.google.com/..."
"""

import json
import argparse
from pathlib import Path
from typing import Any


def assess_spreadsheet_complexity(profile: dict) -> dict[str, Any]:
    """Analyze a profiler output dict and return a complexity assessment."""
    tabs = profile.get("tabs", [])
    cross_sheet_refs = profile.get("cross_sheet_refs", [])

    tab_count = len(tabs)
    total_rows = sum(t.get("row_count", 0) for t in tabs)
    total_columns = sum(len(t.get("columns", [])) for t in tabs)
    total_formula_columns = sum(t.get("formula_columns", 0) for t in tabs)
    cross_ref_count = len(cross_sheet_refs)

    formula_density = total_formula_columns / max(total_columns, 1)

    # Complexity scoring
    score = 0
    if tab_count > 5:
        score += 1
    if tab_count > 10:
        score += 2
    if total_rows > 5000:
        score += 1
    if total_rows > 20000:
        score += 1
    if formula_density > 0.3:
        score += 1
    if cross_ref_count > 5:
        score += 1
    if cross_ref_count > 20:
        score += 2

    if score <= 2:
        complexity_tier = "appliance"
        estimated_build_weeks = 2
    elif score <= 5:
        complexity_tier = "partnership"
        estimated_build_weeks = score
    else:
        complexity_tier = "partnership"
        estimated_build_weeks = min(score + 2, 12)

    recommendation = (
        "Appliance — well-structured data, low formula complexity. Standard pipeline covers most needs."
        if complexity_tier == "appliance"
        else "Partnership — complex spreadsheet interdependency. Human contract hardening and domain modeling recommended."
    )

    return {
        "tab_count": tab_count,
        "total_rows": total_rows,
        "total_columns": total_columns,
        "formula_density": round(formula_density, 2),
        "cross_sheet_ref_count": cross_ref_count,
        "complexity_score": score,
        "complexity_tier": complexity_tier,
        "estimated_build_weeks": estimated_build_weeks,
        "recommendation": recommendation,
    }


def load_profile(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Assess spreadsheet complexity for scoping")
    parser.add_argument("--profile", type=Path, help="Path to profiler output JSON")
    args = parser.parse_args()

    if args.profile:
        profile = load_profile(args.profile)
    else:
        parser.print_help()
        return

    result = assess_spreadsheet_complexity(profile)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest scripts/tests/test_scoping_assessment.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/scoping_assessment.py scripts/tests/test_scoping_assessment.py
git commit -m "feat: add scoping assessment CLI tool"
```

---

## Spec Coverage Check

| Spec section | Covered by |
|-------------|------------|
| Long Term Promise | Task 1 (contract template preamble) |
| Service Phases (Build/Run/Evolve) | Task 1 (Section 1 — Services) |
| Customer Profile (Partnership/Appliance) | Task 5 (complexity_tier output) |
| Onboarding Flow + paid scoping | Task 3 (Scoping SOW), Task 4 (checklist) |
| Contract Maturity Tiers | Task 1 (Section 3 — tier reference) |
| Run Phase Baseline Commitments | Task 1 (Section 1 — Run Phase) |
| Regulatory/Legal Baseline | Task 2 (DPA addendum) |
| Evolve Phase | Task 1 (Section 1 — Evolve Phase) |
| Data & IP Ownership | Task 1 (Section 6 — Data Ownership) |
| Term, Payment, Renewal | Task 1 (Sections 4-5 — Fees, Term) |
| Exit / Transition | Task 1 (Section 5 — termination clause) |
| Design Principles | Implicit in all templates |
