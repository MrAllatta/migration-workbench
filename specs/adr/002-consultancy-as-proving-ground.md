# ADR-002: Consultancy as the funded proving ground

**Date:** 2026-07-15
**Status:** Accepted
**Deciders:** operator (ralph), agent

## Context

ADR-001 established that migration-workbench is a platform for generating bespoke served apps from behavioral specifications. The question remains: how does the platform mature from aspiration into a repeatable, scalable product?

Two live engagements (Vizcarra Guitars and Farm) are currently the primary validation surfaces. Each engagement produces a generated Django app, but it also produces something more valuable: evidence about what the platform gets right, what it gets wrong, and which patterns generalize across verticals.

The risk is that services become the business. The opportunity is that services fund the engine while the engine learns from every engagement.

## Decision

We commit to **consultancy as the funded proving ground** for the platform:

### 1. Every engagement is a paid experiment

Each customer engagement is not a custom software delivery. It is a validation of one or more platform hypotheses: a new vertical archetype, a codegen seam, a behavioral spec pattern, or an import pipeline edge case. The customer funds the work; the platform extracts the learning.

### 2. No customer-specific logic enters the engine

All customer-specific code lives in the product repo. All reusable improvements — adapters, archetypes, view templates, interview flows, validation gates — live in migration-workbench. This protects the IP boundary between engine (platform) and generated app (customer asset).

### 3. Every engagement must improve the engine or the methodology

If an engagement does not produce at least one of the following, it is a consulting project, not a proving-ground project:

- A new or refined view archetype
- A vertical starter kit or domain context template
- A codegen fix or hook point
- A documented interview flow or acceptance gate
- A reusable test fixture or validation rule

### 4. Services/product ratio must glide toward product

Target investment mix over time:

| Phase | Services | Product/Platform | Signal |
|-------|----------|------------------|--------|
| Now | ~90% | ~10% | Two live engagements; engine still being hardened |
| 0.10.x–0.11.x | ~70% | ~30% | First vertical templates extracted |
| 0.12.x–0.13.x | ~50% | ~50% | New known-vertical engagement scoped in one session |
| 1.x | ~20% | ~80% | Platform sold and implemented by certified partners |

If the ratio stalls, the business is a consultancy, not a platform company.

### 5. The consultant playbook becomes the product spec

The methodology that produces reliable outcomes (discovery interview, schema contract review, behavioral spec, interaction contract, view manifest, acceptance validation) is not internal lore. It is a first-class artifact: documented, versioned, and eventually trainable to certified partners.

## Consequences

### Positive

- Live customer data and real workflows stress-test the platform in ways synthetic tests cannot.
- Each vertical engagement builds the template library for the next similar customer.
- The operator is paid to do the R&D that the platform needs.
- The transition from operator-led engagements to partner-led implementations is planned from the start.

### Negative

- Consultancy cash flow can become comfortable and distract from platformization.
- Customers may perceive their engagement as bespoke even when the goal is extraction.
- Balancing immediate customer deliverables against reusable engine improvements requires discipline.

### Risks

- **Services trap:** The team never reduces services ratio. Mitigation: review ratio quarterly and tie roadmap prioritization to extraction goals.
- **Over-generalization:** A pattern from one customer is forced onto others. Mitigation: a pattern enters the platform only after it appears in two distinct engagements or verticals.
- **Customer IP tension:** Customers may claim their generated app patterns are proprietary. Mitigation: clear contracts state that generated code is theirs; methodology, archetypes, and engine improvements are ours.

## Verification

- After Vizcarra and Farm engagements, at least one vertical template or archetype improvement is merged back into migration-workbench.
- Each quarterly review updates the services/product ratio and the vertical template ladder.
- By 1.0.0, a non-operator consultant can scope a known-vertical engagement using the playbook and the workbench alone.
