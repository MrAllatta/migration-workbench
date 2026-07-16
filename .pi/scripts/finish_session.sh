#!/usr/bin/env bash
# finish_session.sh — end-of-session hygiene for the workbench.
#
# Verifies the tree is honest, runs the gate, and commits any dirty state
# with a Conventional Commits message. Refuses to leave planning docs
# uncommitted.

set -euo pipefail

MSG="${MSG:-}"
if [ -z "$MSG" ]; then
    echo "usage: make finish MSG=\"<conventional commit message>\""
    echo "  (or set MSG env var)"
    exit 2
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Check if run from a worktree
if [[ "$(pwd)" == *".worktrees/"* ]]; then
  echo "WARNING: running finish from a worktree."
  echo "Merging should happen from the main checkout."
  echo ""
  echo "To merge this worktree's work:"
  echo "  cd $REPO_ROOT"
  echo "  git merge --squash $(pwd)"
  echo "  git commit -m \"\$MSG\""
  echo "  git worktree remove $(pwd)"
  echo ""
  echo "Continue with finish in worktree? (y/n)"
  read -r answer
  if [ "$answer" != "y" ]; then
    exit 1
  fi
fi

# 1. Planning docs must be staged if modified.
UNSTAGED_PI="$(git diff --name-only -- '.pi/' || true)"
if [ -n "$UNSTAGED_PI" ]; then
    echo "ERROR: planning documents modified but not staged:" >&2
    echo "$UNSTAGED_PI" >&2
    echo "" >&2
    echo "Stage them with: git add -A .pi/" >&2
    echo "Planning docs (.pi/) are source code, not notes." >&2
    exit 1
fi

# 2. Run the gate.
echo "=== running chassis-gate ==="
make chassis-gate

# 3. If the tree is still dirty, commit everything.
if ! git diff --quiet HEAD; then
    echo ""
    echo "=== committing working tree ==="
    git add -A
    git commit -m "$MSG"
fi

# 4. Summary.
BRANCH="$(git branch --show-current)"
AHEAD="$(git rev-list --count --left-right 'origin/'"$BRANCH"'..'"$BRANCH" 2>/dev/null || echo '?')"
LAST="$(git log -1 --oneline)"
echo ""
echo "session finished"
echo "  branch : $BRANCH"
echo "  ahead  : $AHEAD commits ahead of origin/$BRANCH"
echo "  last   : $LAST"
