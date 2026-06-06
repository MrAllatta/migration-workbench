# Ecosystem Queue Lifecycle Reference

> **Status:** Active
> **Date:** 2026-06-05
> **Audience:** All agents writing to or reading from the filesystem queues

## Three-State Lifecycle

```
created ──▶ active ──▶ consumed
```

### created
Entry has been written to the queue. The intended reader has not yet picked it up.
- **Set by:** Writer (agent or human)
- **Action required:** Reader should pick up the entry

### active
Entry has been read. Processing is in progress.
- **Set by:** Reader (via ``wb ecosystem ack <queue> <filename> --status active``)
- **Action required:** Complete processing, then acknowledge as consumed

### consumed
Entry is fully processed and resolved.
- **Set by:** Consumer (via ``wb ecosystem ack <queue> <filename>``)
- **Action required:** None. Entry remains for audit trail.

## Quick Reference

### When to write

| Agent role | Writes to | Calls |
|------------|-----------|-------|
| Meta | next/ | validate before writing |
| Meta | exercise/ | validate before writing |
| Meta | proposals/ | validate before writing |
| Workbench | ready/ | validate before writing, ack next/ as consumed |
| Product | results/ | validate before writing, ack exercise/ as consumed |
| Product | issues/ | validate before writing |
| Product | quality-gates/ | validate before writing |

### When to read and ack

| Agent role | Reads from | After reading |
|------------|------------|---------------|
| Meta | ready/ | ack ready/<entry> as consumed |
| Meta | results/ | ack results/<entry> as consumed |
| Meta | issues/ | ack issues/<entry> as consumed |
| Workbench | next/ | ack next/<entry> as active (start), consumed (done) |
| Product | exercise/ | ack exercise/<entry> as active (start), consumed (done) |
| Human | quality-gates/ | ack quality-gates/<entry> as consumed (after certifying) |
| Human | proposals/ | ack proposals/<entry> as consumed (after squash) |

## Validation Rules

Before writing to any queue, the agent MUST call ``validate_queue_entry()``.
The required fields per queue are:

| Queue | Required fields |
|-------|----------------|
| next/ | ``feature`` |
| ready/ | ``feature`` |
| exercise/ | ``feature`` |
| results/ | ``feature``, ``result`` |
| issues/ | ``title``, ``type``, ``severity`` |
| quality-gates/ | ``meta.name``, ``meta.milestone``, ``tests`` |
| proposals/ | ``milestone`` |

## Health Check

Run ``wb ecosystem health`` to verify all queues are in expected states.
This is recommended:

- Before starting new work (check next/ and exercise/ for pending items)
- After completing a work cycle (verify acknowledgements were recorded)
- Periodically by CI (detect stale entries before they accumulate)
