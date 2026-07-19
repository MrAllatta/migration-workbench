#!/usr/bin/env python3
"""
Opencode session harness — chain loop for epic execution.

Reads specs/ to drive a chain of stories, one subagent per story,
until the epic is complete.

Usage:
    python orchestrate.py                    # chain all pending stories in active epic
    python orchestrate.py e08s01             # run a single story
    python orchestrate.py --epic e08         # chain a specific epic
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# --- Constants -------------------------------------------------------------

_CONTEXT_TRUNCATE_LINE_LIMIT = 300
_CONTEXT_HEAD_LINES = 200
_CONTEXT_TAIL_LINES = 50


# --- YAML helpers -----------------------------------------------------------

def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning an empty dict if it doesn't exist."""
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f)


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write a YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False)


def load_epic(project_dir: Path, epic_id: str) -> dict[str, Any]:
    """Load an epic.yaml by epic ID (prefix match on directory name)."""
    epic_dir = find_epic_dir(project_dir, epic_id)
    epic_path = epic_dir / "epic.yaml"
    if not epic_path.exists():
        print(f"FAIL: epic.yaml not found at {epic_path}", file=sys.stderr)
        sys.exit(1)
    return load_yaml(epic_path)


def find_epic_dir(project_dir: Path, epic_id: str) -> Path:
    """Find the epic directory matching an epic ID prefix."""
    epics_dir = project_dir / "specs" / "epics"
    if not epics_dir.exists():
        print(f"FAIL: specs/epics/ not found", file=sys.stderr)
        sys.exit(1)
    for entry in sorted(epics_dir.iterdir()):
        if entry.is_dir() and entry.name.startswith(f"{epic_id}-"):
            return entry
    print(f"FAIL: epic directory not found for {epic_id}", file=sys.stderr)
    sys.exit(1)


# --- Cursor logic ----------------------------------------------------------

def find_next_story(
    epic: dict[str, Any], exec_status: dict[str, Any]
) -> dict[str, Any] | None:
    """Find the next uncompleted story using execution-status.yaml as cursor.

    The cursor is ``exec_status.active.story_id`` (last completed story).
    Returns the story after the cursor, or the first story if no cursor.
    Returns None if the epic has no more stories.
    """
    stories = epic.get("stories", [])
    if not stories:
        return None

    current_id = exec_status.get("active", {}).get("story_id")
    if not current_id:
        return stories[0]

    idx = next(
        (i for i, s in enumerate(stories) if s["id"] == current_id),
        -1,
    )
    if idx == -1:
        return stories[0]
    if idx + 1 >= len(stories):
        return None
    return stories[idx + 1]


def load_cursor(project_dir: Path) -> dict[str, Any]:
    """Load execution-status.yaml."""
    return load_yaml(project_dir / "specs" / "execution-status.yaml")


def update_cursor(
    project_dir: Path, epic_id: str, story_id: str, status: str = "done"
) -> None:
    """Mark a story complete in execution-status.yaml."""
    exec_path = project_dir / "specs" / "execution-status.yaml"
    data = load_yaml(exec_path)
    data["active"] = {
        "epic_id": epic_id,
        "story_id": story_id,
        "status": status,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    write_yaml(exec_path, data)


def load_active_epic(project_dir: Path) -> str:
    """Load the active epic ID from state.yaml."""
    state = load_yaml(project_dir / "specs" / "state.yaml")
    epic_id = state.get("active_epic_id")
    if not epic_id:
        print("FAIL: no active_epic_id in specs/state.yaml", file=sys.stderr)
        sys.exit(1)
    return epic_id


# --- Prompt formatting -----------------------------------------------------

def load_context_files(
    project_dir: Path, story: dict[str, Any]
) -> list[dict[str, str]]:
    """Pre-digest context files specified in the story definition."""
    context_refs = story.get("context", [])
    if not context_refs:
        return []

    context_files: list[dict[str, str]] = []
    for rel_path in context_refs:
        abs_path = project_dir / rel_path
        try:
            if not abs_path.exists():
                continue
            content = abs_path.read_text()
            lines = content.split("\n")
            if len(lines) > _CONTEXT_TRUNCATE_LINE_LIMIT:
                truncated = (
                    "\n".join(lines[:_CONTEXT_HEAD_LINES])
                    + f"\n\n... ({len(lines) - _CONTEXT_TAIL_LINES} lines omitted) ...\n\n"
                    + "\n".join(lines[-_CONTEXT_TAIL_LINES:])
                )
            else:
                truncated = content
            context_files.append({"path": str(abs_path), "content": truncated})
        except (OSError, PermissionError) as exc:
            print(f"[harness] Warning: could not read context file {abs_path}: {exc}")
    return context_files


def format_prompt(
    story: dict[str, Any],
    epic: dict[str, Any],
    epic_id: str,
    context_files: list[dict[str, str]] | None = None,
) -> str:
    """Build the story prompt from epic/story data and optional context."""
    task_lines: list[str] = []
    tasks = story.get("tasks", [])
    for i, t in enumerate(tasks, 1):
        line = f"{i}. {t['description']}"
        verify = t.get("verify", "")
        if verify:
            line += f"\n   Verify: `{verify}`"
        task_lines.append(line)

    # Context block
    context_block = ""
    if context_files:
        sections: list[str] = []
        for cf in context_files:
            sections.append(f"### {cf['path']}\n\n```\n{cf['content']}\n```")
        if sections:
            context_block = "\n## Context\n\n" + "\n\n".join(sections)

    epic_desc = epic.get("description", "")

    return f"""# Story {story['id']}: {story['title']}

Epic: {epic_id} — {epic['title']}
{epic_desc.strip()}
{context_block}
## Your job
Execute story {story['id']}. Work in small, tested steps.

## Tasks
{chr(10).join(task_lines) or '(no tasks defined)'}

## Constraints
- Work on the active feature branch, NOT on master.
- Run the verification command for each task before moving on.
- When the story is complete, update specs/execution-status.yaml:
  - Set active.epic_id to {epic_id}
  - Set active.story_id to {story['id']}
  - Set active.status to done
  - Set active.completed_at to the current ISO timestamp.
- Commit all changes to the worktree before marking the story done.
  Use a conventional commit message: `{story['id']}: <short description>`.
  Include `last-prompt.md` in the commit — it records the original intent.
- Do NOT start another story in this session.

Begin."""


# --- Story runner ----------------------------------------------------------

def run_story(
    project_dir: Path,
    epic_id: str,
    epic: dict[str, Any],
    story: dict[str, Any],
    *,
    dry_run: bool = False,
) -> str:
    """Prepare a story for execution and print the task parameters.

    In dry_run mode, writes the prompt to last-prompt.md and prints it.
    For actual execution, the orchestrator outputs the task() call that
    the opencode agent should invoke.

    Returns the final status read from execution-status.yaml after the
    agent completes: "done" or "pending".
    """
    # Find the epic directory for artifact output
    epic_dir = find_epic_dir(project_dir, epic_id)

    # Load context files
    context_files = load_context_files(project_dir, story)

    # Format prompt
    prompt = format_prompt(story, epic, epic_id, context_files)

    # Write prompt for inspection
    prompt_path = epic_dir / "last-prompt.md"
    prompt_path.write_text(prompt)
    print(f"[harness] Prompt written to {prompt_path}")

    # Commit the prompt so we record what the author intended
    try:
        subprocess.run(
            ["git", "add", str(prompt_path)],
            cwd=project_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"chore(harness): dispatch {story['id']}"],
            cwd=project_dir,
            check=True,
            capture_output=True,
        )
        print(f"[harness] Committed last-prompt.md")
    except subprocess.CalledProcessError as exc:
        print(f"[harness] Warning: could not commit last-prompt.md: {exc}")

    if dry_run:
        print("\n--- PROMPT ---")
        print(prompt)
        print("--- END PROMPT ---")
        return "dry_run"

    # Print the execution instructions for the opencode agent
    print(f"\n[harness] Story {story['id']}: '{story['title']}'")
    print(f"[harness] To execute this story in opencode, call:")
    print(f"[harness]")
    print(f"[harness]   task(")
    print(f"[harness]       category='deep',")
    print(f"[harness]       load_skills=['test-driven-development', 'verification-before-completion'],")
    print(f"[harness]       prompt=read_file('{prompt_path}')")
    print(f"[harness]   )")
    print(f"[harness]")
    print(f"[harness] After execution, check specs/execution-status.yaml for completion.")

    # Read the cursor to get final status
    exec_status = load_cursor(project_dir)
    active = exec_status.get("active", {})
    if active.get("story_id") == story["id"] and active.get("status") == "done":
        return "done"
    return "pending"


# --- Chain runner ----------------------------------------------------------

def chain(
    project_dir: Path,
    epic_id: str,
    *,
    dry_run: bool = False,
) -> None:
    """Chain through all pending stories in an epic."""
    epic = load_epic(project_dir, epic_id)
    exec_status = load_cursor(project_dir)
    count = 0
    last_id: str | None = None

    print(f"\n--- Chain: epic {epic_id} ---\n")

    next_story = find_next_story(epic, exec_status)
    while next_story:
        if next_story["id"] == last_id:
            print(f"[chain] Cursor stuck at {next_story['id']}. Stopping.")
            break

        last_id = next_story["id"]
        count += 1

        result = run_story(project_dir, epic_id, epic, next_story, dry_run=dry_run)
        print(f"\n[chain] {next_story['id']} → {result}")

        if result != "done":
            print(f"[chain] Chain stopped — {next_story['id']} not marked done.")
            break

        # Reload cursor for next iteration
        exec_status = load_cursor(project_dir)
        next_story = find_next_story(epic, exec_status)

    print(f"\n[chain] Epic {epic_id}: ran {count} story/stories.")


# --- CLI entry point -------------------------------------------------------

def resolve_project_dir() -> Path:
    """Find the project root containing specs/state.yaml."""
    cwd = Path.cwd()
    if (cwd / "specs" / "state.yaml").exists():
        return cwd

    script_dir = Path(__file__).resolve().parent
    for _ in range(6):
        if (script_dir / "specs" / "state.yaml").exists():
            return script_dir.resolve()
        script_dir = script_dir.parent

    print("FAIL: could not find project root (no specs/state.yaml)", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Opencode session harness")
    parser.add_argument(
        "story_id", nargs="?", help="Run a single story (e.g. e08s01)"
    )
    parser.add_argument(
        "--epic", help="Chain a specific epic (default: from specs/state.yaml)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the prompt without executing",
    )
    parser.add_argument(
        "--model",
        help="Model to use for story execution",
    )
    args = parser.parse_args()

    project_dir = resolve_project_dir()

    # Resolve epic ID
    epic_id = args.epic or load_active_epic(project_dir)

    if args.story_id:
        # Single-story mode
        epic = load_epic(project_dir, epic_id)
        stories = epic.get("stories", [])
        target = next((s for s in stories if s["id"] == args.story_id), None)
        if not target:
            print(f"FAIL: story {args.story_id} not found in epic {epic_id}")
            sys.exit(1)

        result = run_story(project_dir, epic_id, epic, target, dry_run=args.dry_run)
        print(f"\nResult: {result}")
        sys.exit(0 if result == "done" else 1)
    else:
        # Chain mode
        chain(project_dir, epic_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()