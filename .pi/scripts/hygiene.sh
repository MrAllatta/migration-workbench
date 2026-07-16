#!/usr/bin/env bash
# Hygiene check — run at session start before booting the next mission.
set -o pipefail

err=0
now=$(date +%s)
five_days=$((5 * 86400))

# 1. Uncommitted portfolio
if ! git diff --quiet -- .pi/portfolio.md 2>/dev/null ||
   ! git diff --cached --quiet -- .pi/portfolio.md 2>/dev/null; then
  echo "  WARN: .pi/portfolio.md has uncommitted changes"
  err=1
fi

# 2. Stale local branches (unmerged to master, older than 5 days)
while IFS= read -r b; do
  b="${b#  }"
  [ -z "$b" ] && continue
  commit_time=$(git log -1 --format=%ct "$b" 2>/dev/null)
  if [ -n "$commit_time" ] && [ $(( (now - commit_time) )) -gt $five_days ]; then
    age_days=$(( (now - commit_time) / 86400 ))
    echo "  STALE: $b (${age_days} days old, not merged to master)"
    err=1
  fi
done <<< "$(git branch --no-merged master --sort=-committerdate 2>/dev/null)"

# 3. Orphaned worktree directories
if [ -d .worktrees ]; then
  for wt_dir in .worktrees/*/; do
    [ -d "$wt_dir" ] || continue
    if ! git worktree list 2>/dev/null | grep -qF "$wt_dir"; then
      echo "  ORPHANED WORKTREE: $wt_dir"
      err=1
    fi
  done
fi

# 4. Stale remote-tracking refs
if git remote get-url origin >/dev/null 2>&1; then
  stale_list=$(git remote prune origin --dry-run 2>&1 | grep 'would prune' | sed 's/^.*would prune //')
  if [ -n "$stale_list" ]; then
    echo "  STALE REMOTE BRANCHES:"
    printf "    %s\n" "$stale_list"
    err=1
  fi
fi

# 5. Current branch check
current=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [ "$current" != "master" ]; then
  echo "  NOTE: on branch '$current', not 'master'"
fi

# 6. Worktree model enforcement — check main checkout branch
main_branch=$(git worktree list 2>/dev/null | grep -v ".worktrees/" | head -1 | awk '{print $3}' | tr -d '[]')
if [ -n "$main_branch" ] && [ "$main_branch" != "master" ]; then
  echo "  VIOLATION: main checkout is on '$main_branch', not 'master'"
  echo "  ~/projects/migration-workbench must always have master checked out."
  err=1
fi

# 7. Active worktree status
worktree_count=$(git worktree list 2>/dev/null | grep -c ".worktrees/" || true)
if [ "$worktree_count" -gt 0 ]; then
  echo "  ACTIVE WORKTREES: $worktree_count"
  git worktree list 2>/dev/null | grep ".worktrees/" | sed 's/^/    /'
fi

if [ "$err" -eq 0 ]; then
  echo "  All clean."
else
  echo "  Run 'make finish' to clean up, or address items manually."
  echo "  Worktree model: all development happens in .worktrees/wt-<slug>"
  exit 1
fi
