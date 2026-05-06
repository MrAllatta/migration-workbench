<!-- discovery-interview-format: draft-1 -->
# Discovery Interview — example

## Top-level

<!-- q: weekly_workflow -->
1. Walk me through what you do with this sheet on a typical Monday.
   > On Monday I open the Orders tab, sort by status, and chase anything still in pending past Friday.

## Per-view questions

### Orders (source tab: Orders)

<!-- q: role tab=Orders -->
- Is **Orders** used by everyone, or a specific role?
  > Finance team only; sales has read access.

- Which fields does your team edit most frequently?
  > _Editable fields inferred: order_id, customer, status_

<!-- q: status tab=Orders field=status -->
- What does moving the **status** field from one value to another mean in your process?
  > open -> pending means invoice cut; pending -> shipped means we put it on the truck; shipped -> closed means payment received.

### Staging (hidden tab — staging/admin)

<!-- q: access tab=Staging -->
- Who has access to **Staging**? Is this an internal-only tab?
  > Internal QA only; never shown to clients. Used for reconciling import errors.

## Workflow actions

<!-- q: weekly_actions -->
- What are the 3–5 things you do in this sheet every week?
  1. Reconcile new orders against the CRM export.
  2. Move pending orders to shipped after the Wednesday warehouse run.
  3. Close out fully-paid orders on Friday afternoon.
