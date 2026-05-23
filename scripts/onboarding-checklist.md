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
