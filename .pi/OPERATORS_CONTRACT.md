# Public Maintainer Contract

This is the operating agreement for the workbench repository. It exists so
that:

- A first-time visitor landing on `origin/master` sees a coherent project.
- The next release can be cut without anxiety.
- The maintainer (and the agent) have an unambiguous answer to "is this
  ready?"

The contract is not cargo cult. Every rule answers a question a visitor or
future-consultant would ask.

---

## The Five Rules

### 1. `master` is what the public sees

`origin` is not a mirror. It is the canonical history. Every minor that is
real lives on `master` and is tagged on the remote. Local-only tags are
drafts, not releases.

### 2. A tag is a promise

You do not tag a commit that is red. You do not tag a commit whose
`pyproject.toml` version does not match the tag. You do not tag a commit
whose changelog entry does not exist. `vX.Y.Z` on the remote means: gate
green, version bumped, changelog honest, ready to be cited.

### 3. Planning docs are public working memory

`.pi/portfolio.md`, `.pi/missions/*/brief.md`, and
`.pi/missions/*/journal.md` are committed, current, and honest. A visitor
reading the portfolio sees the real state. A stale portfolio is a
credibility leak.

### 4. CI is the gate

`.github/workflows/ci.yml` runs the chassis gate. The discipline is to let
it be the authority: do not push red, do not merge around a red build, do
not tag a commit the public CI has not seen pass. Branch protection on
`master` (require CI green) is recommended; the GitHub setting is in
**Settings → Branches → Branch protection rules**.

### 5. The release ritual is the same every time

Predictable means scripted. `make release VERSION=x.y.z` does the same
checks in the same order every time. There is no "I'll do it manually this
once." Manual releases drift; scripted releases accumulate reliability.

---

## Remote Policy

| State | Action |
|-------|--------|
| Local commit on `master`, not pushed | Push at next minor boundary or before any context-switch risk |
| Local tag, not pushed | Same. A local-only tag is a draft, not a release |
| Push on `feat/*` branch | Push freely as backup; do not open PRs unless inviting a reviewer |
| PyPI upload | Blocked until 1.0.0 (PyPI rejects `<= 0.9.3`). See `docs/roadmap.md` |

Push authority: the human owns the push to `origin/master` and to
release tags, unless explicitly delegated to the agent for a specific
release.

---

## Session-Start Ritual — `make hygiene`

Run before booting the next mission. This is the morning sweep: check
that the world is as you left it before you build on top of it.

```bash
make hygiene
```

What it does:
1. Detects uncommitted `.pi/portfolio.md` changes.
2. Lists unmerged local branches older than five days.
3. Finds orphaned `.worktrees/` directories.
4. Shows stale remote-tracking refs (`origin/branch-name` that no
   longer exists upstream).
5. Advises if you are not on `master`.

Exit 0 with "All clean." if nothing is wrong. Exit 1 with actionable
warnings otherwise. Fix what it finds, then start the mission.

---

## Session Ritual — `make finish`

End of any work session. This is the daily hygiene that keeps the tree
trustworthy.

```bash
make finish MSG="feat(views): landing archetype card grid and url routing"
```

What it does:
1. Runs `make chassis-gate` (the oracle).
2. Fails if any `.pi/**` file is modified but not staged.
3. If the tree is dirty, commits all changes with the given message.
4. Prints a one-line summary of branch, ahead/behind, and last commit.

If the gate is red, fix it before `make finish`. Do not use `make finish`
to commit a known-red state. For a known-red WIP, use a normal `git
commit` with a `[WIP]` prefix and note the failure in the mission
journal.

---

## Release Ritual — `make release`

The only sanctioned way to cut a release.

```bash
make release VERSION=0.6.3
```

What it does:
1. Verifies you are on `master` and the tree is clean.
2. Runs `make chassis-gate`. Aborts on red.
3. Verifies `pyproject.toml` `version` matches `VERSION`.
4. Verifies `README.md` has a `### VERSION` changelog entry.
5. Commits any staged release-bookkeeping changes.
6. Creates an annotated tag `vVERSION`.
7. Prints a clear "ready to push" message with the exact `git push`
   commands.

To actually push:

```bash
git push origin master
git push origin v0.6.3
```

Or, if push authority has been explicitly delegated to the agent for this
release:

```bash
make release VERSION=0.6.3 PUSH=1
```

---

## Branch Discipline

From `AGENTS.md`:

- Feature branches insulate `master`. Every mission gets `feat/<slug>`.
- No long-lived branches. Branches older than one week are merged or
  deleted.
- The agent commits on the branch, hammers out edge cases there, and
  squash-merges when green.
- Roadmap maintenance (this contract, `docs/roadmap.md`, `README.md`
  changelog) is not feature work and may land on `master` directly.

Stale-branch check: `git branch -v` should show no branch older than one
week that is not actively being worked.

---

## Cargo Cult We Explicitly Avoid

- A `CONTRIBUTING.md` for a solo project with no contributors yet.
- A `CHANGELOG.md` separate from `README.md` (the README changelog
  already serves).
- Pre-commit hooks that duplicate CI (CI is the gate; local is the dev
  loop).
- Strict branch protection as a wall (it is a backstop, not a prison).
- Manual release steps (use `make release`).

---

## What This Document Is

This is a living operating agreement. It changes when the workflow earns a
better one. Update it as the discipline evolves; do not let it drift from
practice.
