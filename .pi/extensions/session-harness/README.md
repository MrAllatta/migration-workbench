# Session Harness — Phase 0.2

**Short-session harness with chain loop for the migration-workbench.**

One story, one fresh session. The chain advances through the epic until
all stories are marked done. No subprocess. No prompt-pasting.

## Architecture

```
specs/state.yaml + epics/eNN-slug/epic.yaml
              │
              ▼
orchestrate.js  (Node.js, uses pi SDK directly)
              │
              ▼
   createAgentSession(SessionManager.inMemory)
              │  ←── fresh context window per story
              ▼
        session.prompt(story_brief)
              │
              ▼
        agent_settled  →  session.dispose()
              │
              ▼
   Read execution-status.yaml → advance to next story
              │
              ▼
       (loop until all done)
```

## Files

| File | Role |
|------|------|
| `orchestrate.js` | Node.js orchestrator. Uses `createAgentSession()` from the pi SDK directly. No subprocess. |
| `orchestrate.sh` | tmux wrapper. Spawns the orchestrator in a dedicated pane. |
| `index.ts` | pi extension (optional). `/story:run` and `/story:status` for interactive use. |
| `package.json` | Dependencies. Local install of the pi SDK (symlinked from the global install). |

## How to use

### Run one story

```bash
# From the project root:
.p i/extensions/session-harness/orchestrate.sh e05s01
```

This spawns a tmux session named `harness`. The orchestrator creates one
in-process `AgentSession`, sends the story prompt, streams events, and
exits when the agent settles. **One story, one session.**

### Run a chain through an epic

```bash
# Chain all pending stories in the active epic:
.p i/extensions/session-harness/orchestrate.sh
```

The orchestrator reads `specs/state.yaml` to find the active epic, then
runs each story in sequence. After each story, it reads
`specs/execution-status.yaml` to see if the story was marked done.
If yes, it advances to the next story in the epic. The chain stops
when a story is not marked done or the epic is complete.

```bash
# Or specify an epic explicitly:
.p i/extensions/session-harness/orchestrate.sh --epic e05
```

### Attach the tmux session

```bash
tmux attach -t harness
```

You'll see live agent output as each story runs.

## Phase 0.2 features

| Feature | Status |
|---------|--------|
| Run one story in a fresh in-process session | ✅ Done |
| Chain stories through an epic | ✅ Done |
| Use the pi SDK directly (no subprocess) | ✅ Done |
| Stream text deltas and tool events to stdout | ✅ Done |
| Stop chain when a story fails to mark itself done | ✅ Done |
| Persist session state between stories | Each story is ephemeral (clean context) |
| **Not yet** | |
| Failure handling (retry on agent_settled failure) | Phase 0.3 |
| Decide which model to use per epic | Phase 0.3 |
| Persistent session for cross-story context | Probably not needed (clean per story) |
| Tmux session per story (parallelism) | Optional future |

## How the chain advances

The chain uses `specs/execution-status.yaml` as a cursor. Specifically:

- `active.story_id` is set by the agent when a story is done
- The orchestrator finds the next story in the epic after the cursor
- If no cursor exists, the chain starts at the first story
- If the agent fails to mark a story done, the chain stops

The agent is told (in the prompt) to update `execution-status.yaml`
when the story is complete. The chain trusts the agent to do this.

## Requirements

- `node` 22+ (for ESM)
- The pi SDK available as `@earendil-works/pi-coding-agent`
  (installed locally via the symlink in `package.json`)
- `tmux` 3.5+
- A `specs/state.yaml` with `active_epic_id` set
- An epic at `specs/epics/eNN-slug/epic.yaml` with stories

## Why this design

The previous design (Phase 0.1) used a Python orchestrator that spawned
`pi --mode rpc` as a subprocess and communicated via JSON-RPC. The
subprocess overhead was negligible per story, but the chain logic was
missing — each story required manual invocation.

Phase 0.2 uses the pi SDK directly via `createAgentSession()`. This:

- Eliminates the subprocess (cleaner architecture)
- Allows multiple sessions to be created in-process (one per story)
- Aligns with pi's own recommended pattern for automation
- Keeps the orchestrator in the same language as the pi extensions
