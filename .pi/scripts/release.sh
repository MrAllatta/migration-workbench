#!/usr/bin/env bash
# release.sh — the only sanctioned way to cut a workbench release.
#
# Validates state, runs the gate, verifies version + changelog, commits,
# tags. Does not push by default.

set -euo pipefail

VERSION="${1:-${VERSION:-}}"
PUSH="${PUSH:-0}"

if [ -z "$VERSION" ]; then
    echo "usage: make release VERSION=x.y.z [PUSH=1]"
    exit 2
fi

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: VERSION must be semver (got: $VERSION)" >&2
    exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# 1. Must be on master.
BRANCH="$(git branch --show-current)"
if [ "$BRANCH" != "master" ]; then
    echo "ERROR: releases must be cut from master (currently on $BRANCH)" >&2
    exit 1
fi

# 2. Working tree must be clean.
if ! git diff --quiet HEAD; then
    echo "ERROR: working tree is dirty. Commit or revert before releasing." >&2
    git status --short >&2
    exit 1
fi

# 3. Run the gate.
echo "=== running chassis-gate ==="
make chassis-gate

# 4. Verify pyproject.toml version matches.
PYPROJECT_VERSION="$(grep -E '^version' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
if [ "$PYPROJECT_VERSION" != "$VERSION" ]; then
    echo "ERROR: pyproject.toml version is '$PYPROJECT_VERSION', expected '$VERSION'" >&2
    echo "  update: version = \"$VERSION\"" >&2
    exit 1
fi

# 5. Verify README changelog has a ### x.y.z entry.
if ! grep -qE "^### $VERSION " README.md; then
    echo "ERROR: README.md has no '### $VERSION' changelog entry" >&2
    echo "  add a '### $VERSION (local)' section above 0.6.x entries" >&2
    exit 1
fi

# 6. Tag.
TAG="v$VERSION"
if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "ERROR: tag $TAG already exists" >&2
    exit 1
fi

git tag -a "$TAG" -m "release: $VERSION"

echo ""
echo "=== release prepared ==="
echo "  version : $VERSION"
echo "  tag     : $TAG"
echo "  commit  : $(git rev-parse --short HEAD)"
echo ""
echo "Next steps:"
echo "  git push origin master"
echo "  git push origin $TAG"
echo ""
if [ "$PUSH" = "1" ]; then
    echo "PUSH=1 set: pushing master and $TAG"
    git push origin master
    git push origin "$TAG"
else
    echo "To push now, either run the commands above or re-run with PUSH=1"
    echo "(PUSH=1 requires explicit delegation of push authority to the agent.)"
fi
