import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import YAML from "yaml";

interface Task {
  description: string;
  verify: string;
}

interface Story {
  id: string;
  title: string;
  tasks: Task[];
}

interface Epic {
  id: string;
  title: string;
  description?: string;
  verify?: string;
  stories: Story[];
}

interface State {
  active_epic_id?: string;
  active_story_id?: string;
}

function loadYaml<T>(path: string): T | null {
  if (!existsSync(path)) {
    return null;
  }
  return YAML.parse(readFileSync(path, "utf8")) as T;
}

function findStory(epic: Epic, storyId: string): Story | null {
  return epic.stories.find((story) => story.id === storyId) ?? null;
}

function formatStoryPrompt(storyId: string, story: Story, epic: Epic, state: State): string {
  const tasks = story.tasks
    .map((task, index) => `${index + 1}. ${task.description}\n   Verify: \`${task.verify}\``)
    .join("\n");

  return [
    `# Story ${storyId}: ${story.title}`,
    "",
    `Epic: ${epic.id} — ${epic.title}`,
    epic.description ? `\n${epic.description.trim()}` : "",
    "",
    "## Your job",
    `Execute story ${storyId} from the epic above. Work in small, tested steps.`,
    "",
    "## Tasks",
    tasks,
    "",
    "## Constraints",
    "- Do NOT work directly on `master`. Use the active feature branch if one exists.",
    "- Run the verification command for each task before marking it done.",
    "- When the story is complete, update `specs/execution-status.yaml`:",
    `  - Set \`active.epic_id\` to \`${epic.id}\`.`,
    `  - Set \`active.story_id\` to \`${storyId}\`.`,
    "  - Set `active.status` to `done`.",
    `  - Set \`active.completed_at\` to the current ISO timestamp.`,
    "- Do NOT start another story in this session. One story, one session.",
    "",
    "Begin.",
  ].join("\n");
}

export default function (pi: ExtensionAPI) {
  pi.registerCommand("story:run", {
    description: "Execute a single story from specs/ in this fresh session",
    handler: async (args, ctx) => {
      const storyId = args.trim();
      if (!storyId) {
        ctx.ui.notify("Usage: /story:run <story-id>", "error");
        return;
      }

      const statePath = join(ctx.cwd, "specs", "state.yaml");
      const state = loadYaml<State>(statePath);
      if (!state) {
        ctx.ui.notify(`Could not read ${statePath}`, "error");
        return;
      }

      const epicId = state.active_epic_id;
      if (!epicId) {
        ctx.ui.notify("No active epic in specs/state.yaml", "error");
        return;
      }

      const epicPath = join(ctx.cwd, "specs", "epics", epicId, "epic.yaml");
      const epic = loadYaml<Epic>(epicPath);
      if (!epic) {
        ctx.ui.notify(`Could not read epic ${epicId} at ${epicPath}`, "error");
        return;
      }

      const story = findStory(epic, storyId);
      if (!story) {
        ctx.ui.notify(`Story ${storyId} not found in epic ${epicId}`, "error");
        return;
      }

      const prompt = formatStoryPrompt(storyId, story, epic, state);

      // Write the prompt to a file so the orchestrator (and the human) can inspect it.
      const promptPath = join(ctx.cwd, ".pi", "extensions", "session-harness", "last-prompt.md");
      writeFileSync(promptPath, prompt, "utf8");

      ctx.ui.notify(`Dispatching story ${storyId}...`, "info");
      await ctx.sendUserMessage(prompt);
    },
  });

  pi.registerCommand("story:status", {
    description: "Show the active story and epic from specs/state.yaml",
    handler: async (_args, ctx) => {
      const statePath = join(ctx.cwd, "specs", "state.yaml");
      const state = loadYaml<State>(statePath);
      if (!state) {
        ctx.ui.notify("Could not read specs/state.yaml", "error");
        return;
      }
      ctx.ui.setWidget("story-status", [
        `Active epic:  ${state.active_epic_id ?? "(none)"}`,
        `Active story: ${state.active_story_id ?? "(none)"}`,
        "",
        "Use /story:run <story-id> to execute a story in this session.",
      ]);
    },
  });

  pi.on("agent_settled", async (_event, ctx) => {
    const sessionName = ctx.sessionManager.getSessionName?.() ?? "";
    if (sessionName.startsWith("story-")) {
      ctx.ui.notify(`Session ${sessionName} settled. Check specs/execution-status.yaml for results.`, "info");
    }
  });
}
