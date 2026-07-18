#!/usr/bin/env bash
# Phase 0.2 short-session harness — tmux entry point.
#
# Spawns a fresh pi session per story, chains stories through an epic
# until all are marked done. Streams agent output to a dedicated tmux pane.
#
# Usage:
#   .pi/extensions/session-harness/orchestrate.sh                 # chain all pending stories in active epic
#   .pi/extensions/session-harness/orchestrate.sh e05s01          # run a single story, no chain
#   .pi/extensions/session-harness/orchestrate.sh --epic e05      # chain a specific epic
#
# Implementation: orchestrate.ts runs the AgentSession in-process via
# the pi SDK. No subprocess. Each story gets a clean context window.

set -euo pipefail

project_dir="$(cd "$(dirname "$0")/../../.." && pwd)"
extension_dir="$project_dir/.pi/extensions/session-harness"
session_name="harness"
safe_session_name="$(printf '%s' "$session_name" | tr -c '[:alnum:]_.-=' '-')"

# Kill any existing tmux session with the same name.
if tmux has-session -t "$safe_session_name" 2>/dev/null; then
  tmux kill-session -t "$safe_session_name"
fi

# The script needs to find the project root (for specs/) and have
# access to its node_modules (for the pi SDK). We cd into the extension
# directory so node_modules resolution works, but the script walks up
# to find specs/state.yaml to determine the project root.
tmux new-session -d -s "$safe_session_name" \
  -c "$project_dir" \
  "cd '$extension_dir' && node orchestrate.js $*; echo '--- Done ---'; read"

echo "Spawned: $safe_session_name"
echo "Attach:  tmux attach -t $safe_session_name"
echo ""
echo "The orchestrator uses the pi SDK to create sessions in-process,"
echo "chaining stories one at a time. Each story has a clean context."
echo "Attach the tmux session to see live agent output."
