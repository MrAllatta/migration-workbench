# Session Harness — Opencode

Chain loop for running epics in opencode. One story, one subagent.

## Usage

### Run one story

```bash
python .opencode/extensions/session-harness/orchestrate.py e08s01
```

Prints the task() invocation. The agent reads `last-prompt.md` and calls
the task to execute the story.

### Run a chain through an epic

```bash
python .opencode/extensions/session-harness/orchestrate.py
```

Reads `specs/state.yaml` for the active epic, then runs each pending
story until the epic is complete.

### Dry run (preview prompt without executing)

```bash
python .opencode/extensions/session-harness/orchestrate.py e08s01 --dry-run
```

## Architecture

```
specs/state.yaml + specs/epics/eNN-slug/epic.yaml
              │
              ▼
orchestrate.py  (Python, reads YAML, formats prompts)
              │
              ▼
   Writes last-prompt.md  →  Agent reads and calls task()
              │
              ▼
   Agent updates specs/execution-status.yaml
              │
              ▼
   Chain reads cursor, advances to next story
```

## Design

- **One story, one subagent.** Each story gets a fresh subagent via
  `task()` with its own context window.
- **Shared contract.** Both pi and opencode harnesses read the same
  `specs/` YAML files. Agent behavior is identical.
- **YAML cursor.** The chain uses `execution-status.yaml` as a cursor.
  The agent marks stories done, the harness advances to the next one.
