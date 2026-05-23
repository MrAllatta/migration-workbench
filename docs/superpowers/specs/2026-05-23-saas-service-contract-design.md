# SaaS Service Contract Design

> **Context:** migration-workbench is evolving from a PyPI library shipped to product repos into a hosted service — operators turn messy spreadsheets into deployed Django apps on Fly.io. This document defines the customer service contract: what we promise, how we deliver, and how the promise evolves as the platform matures.

---

## The Long Term Promise

> We turn your spreadsheets into a working Django app. We host it, back it up, and keep it secure. As the platform improves, your app improves. If you ever want to leave, you take your data, your code, and a playbook to run it yourself — no locks, no friction. Every engagement teaches the platform, and every customer after you benefits from what we learn.

This statement is the north star for all contract terms below. Every term should reinforce it.

---

## Service Phases

The contract covers three phases:

### Build (one-time fee)

The full pipeline against the customer's spreadsheets:

1. **Connect** — authenticate to source (Google Sheets / Coda), validate access
2. **Profile** — discover tabs, classify data, identify entities and relationships
3. **Contract** — generate schema contract YAML, then **human hardening session** with the customer (this is where high-touch judgment lives and where the boundary of automation is negotiated)
4. **Generate** — produce Django models, admin, import commands
5. **Import** — run preflight, validate, apply data
6. **Deploy** — single-tenant Fly.io app, SQLite + Litestream, custom domain

The customer approves the schema contract before codegen begins. This is the critical human judgment checkpoint.

### Run (monthly recurring)

The app is live and supported. See Contract Maturity Tiers below for what this includes at each stage of platform evolution.

### Evolve (as needed)

Contract updates, schema changes, new features. See The Evolve Phase below.

---

## Customer Profile

Two modes, same contract framework:

| Mode | Description | Current state |
|------|-------------|---------------|
| **Partnership** | High-touch, deep domain modeling. Workbench team learns the customer's business, tunes domain context, hand-hardens contracts. | This is our current reality (farm, vizcarra-guitars, jewelry). |
| **Appliance** | Lower-touch, standardized pipeline. Customer's spreadsheets are well-structured; automation covers most of the work. | This is the target for new customers as the platform matures. |

Both modes use the same pipeline. The difference is the depth of human involvement in the Contract and Evolve phases.

---

## Onboarding Flow

The process from "interested" to "live":

1. **Discovery call** — free, 30min video. Understand the business, spreadsheets, workflows, and user needs. Determine if there's a fit.

2. **Source access setup** — customer shares Google Drive folder / Coda workspace. Operator configures auth and validates access for scoping.

3. **Paid scoping contract** — fixed fee. Operator profiles the spreadsheets and produces a complexity assessment: tab count, formula density, cross-ref complexity, entity discovery. Deliverable: a written assessment with estimated build cost range and timeline. Customer gets valuable insight into their own project.

4. **Build contract + DPA** — if the customer proceeds, the scoping fee credits toward the build. Standard service contract plus DPA addendum is signed.

5. **Build sprint** — 2–6 weeks. Weekly check-in calls. **Critical milestone: schema contract review** — the customer must understand and approve the mapping between their spreadsheets and the Django models before codegen begins. This is where human judgment is most visible and where Partnership vs Appliance distinction matters most.

6. **UAT period** — 1–2 weeks. Customer tests the deployed app against their spreadsheets. Operator fixes issues found.

7. **Go-live** — app is live. Customer starts using it in production. Monthly billing begins.

8. **Tier 1 run phase** — operator hosts, monitors, and backs up. Quarterly check-in calls.

---

## Contract Maturity Tiers

The platform is operated by a solo operator (at least 1-2 years). The contract must be honest about its own maturity by naming the current tier and committing to a progression path.

| Tier | Phase | What you get | Automation level |
|------|-------|-------------|-----------------|
| **Tier 1 — Current** | Deploy + UAT | App is on Fly.io. Operator walks customer through UAT. Litestream replication is running but restores are manual/on-request. Security patches applied when operator has capacity. | Manual |
| **Tier 2 — Stable** | Backed up + monitored | Automated Litestream backup drills every 90 days. Health monitoring with operator alerting. Security patches within 14 days of critical CVE. Documented restore procedure. | Semi-automated |
| **Tier 3 — Mature** | Managed + evolving | All of Tier 2 plus: automated source re-sync, self-service restore, published status page, defined support hours, schema evolution path, feature request process. | Automated |

**The contract names the current tier and commits to progression on an operator-defined timeline.** Customers sign knowing what they get now and what's coming. The contract updates (with customer consent) as each tier threshold is crossed.

---

## Run Phase — Baseline Commitments

At Tier 1, the baseline promise is:

- **Hosting** — single-tenant Fly.io VM, health-checked, auto-restart
- **Backups** — Litestream replication running; restores available on request
- **Security patches** — applied as operator capacity allows
- **Monitoring** — `/healthz` endpoint; operator watches for failures

**Explicit exclusions:**
- No SLA or uptime guarantee (yet)
- No automated restore drills (yet)
- No phone support — email/async only
- No custom feature development in the monthly fee
- No schema changes without a new Evolve engagement

---

## Regulatory / Legal Baseline

The contract includes a Data Processing Agreement (DPA) as a standard addendum. The baseline:

**Data handling:**
- Customer data stored in single-tenant SQLite on Fly.io (ewr region)
- Litestream replicates to S3 (same region) for backup
- Sub-processors disclosed: Fly.io (infrastructure), Tigris/S3 (backup storage), GitHub (repo handoff on exit)
- Data retention: customer data retained for 30 days after cancellation, then purged

**Breach notification:**
- Operator commits to notice within 72 hours of discovering a data breach

**Right to deletion:**
- Exercised via the exit process: full data export delivered to customer, then platform-side wipe

**Explicitly excluded:**
- No HIPAA/BAA — contract states service is not designed for protected health information
- No PCI DSS — contract states service is not designed for payment card data
- No SOC 2 — premature for solo operator stage
- No EU Standard Contractual Clauses — deferred until EU customer demand arises

**Principle:** The exit promise (full data export + 30-day retention + wipe) satisfies most GDPR/CCPA data rights without a formal compliance program. The contract makes this explicit.

---

## The Evolve Phase — How Change Happens

**Included in monthly (all tiers):**
- Security patches and dependency updates
- Minor admin improvements that come from platform improvements
- Data restore on request (manual at Tier 1, self-service at Tier 3)

**Included for Partnership customers (Tier 2+):**
- Schema evolution: add fields, modify types, add computed fields
- New import mappings from changed source spreadsheets
- Quarterly check-in: "has your business changed? Do your spreadsheets look different?"

**Billed separately:**
- New features beyond current contract scope
- Custom admin views, custom workflows, third-party integrations
- Additional data sources beyond original scope

**Upgrade path:** Partnership ↔ Appliance transitions are negotiated at renewal. The customer's fully-owned repo makes this clean.

---

## Data & IP Ownership

**Customer owns:**
- Their source data (spreadsheets, CSVs, Coda docs)
- Their business data loaded into the Django app
- Custom configurations, field mappings, business rules defined during Build
- Their domain (`customer.fly.dev` or custom)
- The **entire generated codebase and GitHub repo** — handed over with self-deploy instructions
- A perpetual, unrestricted license to use all delivered code

**We own:**
- The migration-workbench platform (connectors, profiler, codegen, import runtime)
- The deployment infrastructure patterns (Fly.io config, Litestream setup, CI/CD scaffold)
- **The learning** — domain context improvements, contract patterns, entity definitions, vocabulary — anonymized and generalized back into the platform

**Exit / Transition:**
- Customer cancels with 30 days notice
- On cancellation: customer receives a GitHub repo with generated code + data export + self-deploy README
- The repo includes Fly.io deploy steps and a functional `Makefile`
- Data export: SQLite dump + CSV exports of all tables
- Transition support: optional paid engagement to help the customer's team take over

---

## Term, Payment, and Renewal

**Scoping phase:**
- Fixed fee, paid upfront
- Deliverable: complexity assessment with build cost estimate and timeline
- Credits toward the Build phase if customer proceeds

**Build phase:**
- Fixed-price or time-and-materials based on scoping assessment
- Typical duration: 2-6 weeks
- Deliverable: deployed, UAT-approved Django app

**Run phase:**
- Month-to-month or annual prepay
- Pricing based on Fly.io resource profile (tiny/small/small-plus from `spaces.yml`)
- Auto-renews unless cancelled

**Evolve phase:**
- Separate SOW per engagement, or retainer model

---

## Design Principles

1. **Trust over leverage** — the exit promise (you can leave with everything) builds more trust than lock-in ever could
2. **Honest maturity** — name the current tier; don't over-promise
3. **Compounding value** — every engagement teaches the platform; all customers benefit
4. **Human judgment is the product** — the boundary of what can be automated vs. what needs expert oversight is the actual value being delivered
5. **Small business, not enterprise** — the mission is breaking the enterprise software ecosystem for small business: spreadsheets → deployed app, no sales cycle, no vendor lock-in

---

## Future Considerations

- When the platform reaches multi-tenant maturity (roadmap 0.5.0+), Partnership customers migrate from single-tenant Fly deploys to the shared platform — or stay on their own instance
- The contract should explicitly preserve this migration right
- Pricing automation (metering, invoicing, dunning) is out of scope until Tier 2+ stabilization
