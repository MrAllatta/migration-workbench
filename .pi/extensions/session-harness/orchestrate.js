#!/usr/bin/env node
/**
 * Phase 0.2 — short-session orchestrator with chain loop.
 *
 * Uses the pi SDK to create sessions in-process (no subprocess).
 * Reads specs/ files to drive a chain of stories, one session per story,
 * until the epic is complete.
 *
 * Usage:
 *     node orchestrate.js                          # chain all pending stories in active epic
 *     node orchestrate.js e05s01                   # run a single story
 *     node orchestrate.js --epic e05               # chain a specific epic
 *
 * Design:
 *     Each story gets a fresh in-process AgentSession with a clean
 *     context window. Sessions are ephemeral (in-memory). The chain
 *     advances based on execution-status.yaml's active.story_id cursor.
 */

import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { parse } from "yaml";
import {
  createAgentSession,
  DefaultResourceLoader,
  getAgentDir,
  SessionManager,
} from "@earendil-works/pi-coding-agent";

// --- Resolution -----------------------------------------------------------

// Walk up from the script's directory to find a project root
// that contains specs/state.yaml.
function resolveProjectDir(scriptDir) {
  const cwd = process.cwd();
  if (existsSync(join(cwd, "specs", "state.yaml"))) return cwd;
  let dir = scriptDir;
  for (let i = 0; i < 6; i++) {
    const candidate = join(dir, "..");
    if (existsSync(join(candidate, "specs", "state.yaml"))) return candidate;
    dir = candidate;
  }
  return cwd;
}

// --- Helpers ---------------------------------------------------------------

function loadYaml(path) {
  if (!existsSync(path)) {
    throw new Error(`File not found: ${path}`);
  }
  return parse(readFileSync(path, "utf8"));
}

function findEpicDir(projectDir, epicId) {
  const epicsDir = join(projectDir, "specs", "epics");
  if (!existsSync(epicsDir)) return null;
  for (const entry of readdirSync(epicsDir)) {
    if (entry.startsWith(epicId + "-")) {
      return join(epicsDir, entry);
    }
  }
  return null;
}

function findNextStory(epic, execStatus) {
  // The chain uses execution-status.yaml's `active.story_id` as a cursor.
  const currentId = execStatus.active?.story_id;
  if (!currentId) {
    return epic.stories?.[0] ?? null;
  }
  const idx = epic.stories.findIndex((s) => s.id === currentId);
  if (idx === -1) return epic.stories?.[0] ?? null;
  return epic.stories[idx + 1] ?? null;
}

function formatPrompt(story, epic, epicId, contextFiles) {
  const tasks = story.tasks ?? [];
  const taskLines = [];
  for (let i = 0; i < tasks.length; i++) {
    const t = tasks[i];
    const verify = t.verify ? `\n   Verify: \`${t.verify}\`` : "";
    taskLines.push(`${i + 1}. ${t.description}${verify}`);
  }

  // Build context block from pre-digested source files
  let contextBlock = "";
  if (contextFiles && contextFiles.length > 0) {
    const contextLines = [];
    for (const cf of contextFiles) {
      if (cf.content) {
        // Truncate large files: first 200 lines + last 50
        const lines = cf.content.split("\n");
        let shown;
        if (lines.length > 300) {
          shown = lines.slice(0, 200).join("\n")
            + `\n\n... (${lines.length - 250} lines omitted) ...\n\n`
            + lines.slice(-50).join("\n");
        } else {
          shown = cf.content;
        }
        contextLines.push(
          `### ${cf.path}\n\n\`\`\`\n${shown}\n\`\`\``
        );
      }
    }
    if (contextLines.length > 0) {
      contextBlock = [
        "\n## Context",
        "\nPre-digested source files for this story:\n",
        contextLines.join("\n\n"),
      ].join("\n");
    }
  }

  return [
    `# Story ${story.id}: ${story.title}`,
    "",
    `Epic: ${epicId} — ${epic.title}`,
    epic.description ? `\n${epic.description.trim()}\n` : "",
    contextBlock,
    "## Your job",
    `Execute story ${story.id}. Work in small, tested steps.`,
    "",
    "## Tasks",
    taskLines.length > 0 ? taskLines.join("\n") : "(no tasks defined for this story)",
    "",
    "## Constraints",
    "- Work on the active feature branch, NOT on master.",
    "- Run the verification command for each task before moving on.",
    "- When the story is complete, update specs/execution-status.yaml:",
    `  - Set active.epic_id to ${epicId}`,
    `  - Set active.story_id to ${story.id}`,
    "  - Set active.status to done",
    "  - Set active.completed_at to the current ISO timestamp.",
    "- Do NOT start another story in this session.",
    "",
    "Begin.",
  ].join("\n");
}

// --- Metrics tracker -------------------------------------------------------

class StoryMetrics {
  constructor(storyId) {
    this.storyId = storyId;
    this.modelProvider = null;
    this.modelId = null;
    this.startTime = null;
    this.endTime = null;
    this.turns = 0;
    this.toolCalls = {}; // tool name -> count
    this.toolErrors = {}; // tool name -> count
    this.tokens = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
    this.costUsd = 0;
    this.thinkingChars = 0;
    this.firstToolAt = null;
    this.lastToolAt = null;
    this.toolLatencyMs = 0;
  }

  attachSession(session) {
    if (session.model) {
      this.modelProvider = session.model.provider;
      this.modelId = session.model.id;
    }
  }

  record(event) {
    switch (event.type) {
      case "agent_start":
        if (!this.startTime) this.startTime = Date.now();
        this.turns++;
        break;
      case "agent_end":
        // each turn completed; not a final signal
        break;
      case "tool_execution_start": {
        const name = event.toolName;
        this.toolCalls[name] = (this.toolCalls[name] || 0) + 1;
        const now = Date.now();
        if (!this.firstToolAt) this.firstToolAt = now;
        this.lastToolAt = now;
        break;
      }
      case "tool_execution_end": {
        if (event.isError) {
          const name = event.toolName;
          this.toolErrors[name] = (this.toolErrors[name] || 0) + 1;
        }
        if (this.lastToolAt) this.toolLatencyMs += Date.now() - this.lastToolAt;
        break;
      }
      case "message_update": {
        const e = event.assistantMessageEvent;
        if (e?.type === "thinking_delta" && e.delta) {
          this.thinkingChars += e.delta.length;
        }
        break;
      }
      case "message_end": {
        const msg = event.message;
        if (msg?.usage) {
          this.tokens.input += msg.usage.input || 0;
          this.tokens.output += msg.usage.output || 0;
          this.tokens.cacheRead += msg.usage.cacheRead || 0;
          this.tokens.cacheWrite += msg.usage.cacheWrite || 0;
          if (msg.usage.cost?.total) this.costUsd += msg.usage.cost.total;
        }
        // Capture model from the first assistant message
        if (msg?.model && !this.modelId) {
          this.modelId = msg.model;
          this.modelProvider = msg.provider;
        }
        break;
      }
    }
  }

  finish() {
    this.endTime = Date.now();
  }

  durationSec() {
    if (!this.startTime || !this.endTime) return 0;
    return ((this.endTime - this.startTime) / 1000).toFixed(1);
  }

  print() {
    const totalTools = Object.values(this.toolCalls).reduce((a, b) => a + b, 0);
    const toolList = Object.entries(this.toolCalls)
      .map(([name, n]) => `${name}=${n}`)
      .join(" ");
    const errorList = Object.entries(this.toolErrors)
      .map(([name, n]) => `${name}=${n}`)
      .join(" ");
    const model = this.modelProvider && this.modelId
      ? `${this.modelProvider}/${this.modelId}`
      : "(unknown)";
    const tokens = [
      `in=${formatNum(this.tokens.input)}`,
      `out=${formatNum(this.tokens.output)}`,
      `cacheR=${formatNum(this.tokens.cacheRead)}`,
      `cacheW=${formatNum(this.tokens.cacheWrite)}`,
    ].join(" ");

    const lines = [
      `=== metrics: ${this.storyId} ===`,
      `  model:    ${model}`,
      `  duration: ${this.durationSec()}s`,
      `  turns:    ${this.turns}`,
      `  tools:    ${totalTools} total (${toolList || "none"})`,
      `  errors:   ${errorList || "none"}`,
      `  tokens:   ${tokens}`,
      `  cost:     $${this.costUsd.toFixed(4)}`,
      `  thinking: ${formatNum(this.thinkingChars)} chars`,
    ];
    process.stdout.write(`\n${lines.join("\n")}\n`);
  }

  toJSON() {
    return {
      storyId: this.storyId,
      model: this.modelProvider && this.modelId
        ? `${this.modelProvider}/${this.modelId}`
        : null,
      durationSec: parseFloat(this.durationSec()),
      turns: this.turns,
      toolCalls: this.toolCalls,
      toolErrors: this.toolErrors,
      tokens: this.tokens,
      costUsd: this.costUsd,
      thinkingChars: this.thinkingChars,
    };
  }
}

function formatNum(n) {
  if (n >= 1000) return (n / 1000).toFixed(1) + "K";
  return String(n);
}

// --- Session runner --------------------------------------------------------

async function runStory(projectDir, epicId, epic, story, opts = {}) {
  const promptDir = opts.epicDir || join(projectDir, "specs", "epics", epicId);
  // Load context files if the story defines them
  const contextFiles = [];
  if (story.context && Array.isArray(story.context)) {
    for (const relPath of story.context) {
      const absPath = join(projectDir, relPath);
      if (existsSync(absPath)) {
        try {
          const content = readFileSync(absPath, "utf8");
          contextFiles.push({ path: relPath, content });
        } catch {}
      }
    }
  }
  const prompt = formatPrompt(story, epic, epicId, contextFiles);
  const sessionName = `story-${story.id}`;
  const metrics = new StoryMetrics(story.id);
  const verbose = opts.verbose || false;

  // Write prompt to a file for inspection
  try {
    writeFileSync(join(promptDir, "last-prompt.md"), prompt, "utf8");
  } catch {}

  // Create a fresh in-memory session
  const loader = new DefaultResourceLoader({
    cwd: projectDir,
    agentDir: getAgentDir(),
  });
  await loader.reload();

  const { session } = await createAgentSession({
    cwd: projectDir,
    sessionManager: SessionManager.inMemory(projectDir),
    resourceLoader: loader,
    tools: ["read", "bash", "write", "edit", "grep", "find", "ls"],
  });

  metrics.attachSession(session);

  let settled = false;
  const unsub = session.subscribe((event) => {
    metrics.record(event);
    if (verbose) return; // verbose mode prints raw events instead
    switch (event.type) {
      case "message_update": {
        const e = event.assistantMessageEvent;
        if (e?.type === "text_delta") process.stdout.write(e.delta);
        else if (e?.type === "text_end") process.stdout.write("\n");
        else if (e?.type === "thinking_delta" && opts.showThinking) {
          // optional: show thinking in dim text
          process.stdout.write(`\x1b[2m[thinking] ${e.delta}\x1b[0m`);
        }
        break;
      }
      case "tool_execution_start":
        process.stdout.write(`\n[${sessionName}] (tool: ${event.toolName})\n`);
        break;
      case "tool_execution_end":
        if (event.isError) process.stdout.write(`[${sessionName}] (tool errored)\n`);
        break;
      case "agent_settled":
        settled = true;
        break;
    }
  });

  process.stdout.write(`\n=== ${sessionName} ===\n`);
  process.stdout.write(`${new Date().toISOString()} Starting ${story.id}\n\n`);

  try {
    await session.prompt(prompt);
  } catch (err) {
    process.stderr.write(`[${sessionName}] prompt error: ${err.message}\n`);
    metrics.finish();
    unsub();
    session.dispose();
    metrics.print();
    return "error";
  }

  if (!settled) await new Promise((r) => setTimeout(r, 1000));

  unsub();
  session.dispose();
  metrics.finish();

  // Result: did the agent mark the story done?
  const execPath = join(projectDir, "specs", "execution-status.yaml");
  if (!existsSync(execPath)) {
    metrics.print();
    return "error";
  }
  const status = loadYaml(execPath);
  const result = (status.active?.story_id === story.id && status.active?.status === "done")
    ? "done"
    : "pending";
  metrics.print();
  return result;
}

// --- Main ------------------------------------------------------------------

async function main() {
  const args = process.argv.slice(2);
  const scriptDir = new URL(".", import.meta.url).pathname;
  const projectDir = resolveProjectDir(scriptDir);

  let explicitEpic = null;
  let explicitStory = null;
  let opts = { verbose: false, showThinking: false };
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--epic" && i + 1 < args.length) explicitEpic = args[++i];
    else if (args[i] === "--verbose") opts.verbose = true;
    else if (args[i] === "--show-thinking") opts.showThinking = true;
    else if (!args[i].startsWith("--")) explicitStory = args[i];
  }

  if (opts.verbose) {
    opts.showThinking = true; // verbose implies show thinking
  }

  // Read state
  const statePath = join(projectDir, "specs", "state.yaml");
  const state = loadYaml(statePath);
  const epicId = explicitEpic ?? state.active_epic_id;
  if (!epicId) {
    console.error(`FAIL: no active_epic_id — set it in specs/state.yaml or pass --epic`);
    process.exit(1);
  }

  const epicDir = findEpicDir(projectDir, epicId);
  if (!epicDir) {
    console.error(`FAIL: epic directory not found for ${epicId}`);
    process.exit(1);
  }
  const epicPath = join(epicDir, "epic.yaml");
  const epic = loadYaml(epicPath);

  const execPath = join(projectDir, "specs", "execution-status.yaml");
  let execStatus = loadYaml(execPath);

  // Single-story mode
  if (explicitStory) {
    const target = epic.stories.find((s) => s.id === explicitStory);
    if (!target) {
      console.error(`FAIL: story ${explicitStory} not found in epic ${epicId}`);
      process.exit(1);
    }
    console.log(`\n--- Single: ${explicitStory} ---\n`);
    const result = await runStory(projectDir, epicId, epic, target, { ...opts, epicDir });
    console.log(`\nResult: ${result}`);
    process.exit(result === "done" ? 0 : 1);
  }

  // Chain mode
  console.log(`\n--- Chain: epic ${epicId} ---`);
  let count = 0;
  const start = Date.now();
  let next = findNextStory(epic, execStatus);
  let lastId = null;

  while (next) {
    if (next.id === lastId) {
      console.log(`[chain] Cursor stuck at ${next.id}. Stopping.`);
      break;
    }
    lastId = next.id;
    count++;
    const result = await runStory(projectDir, epicId, epic, next, { ...opts, epicDir });
    console.log(`\n[chain] ${next.id} → ${result}`);
    if (result !== "done") {
      console.log(`[chain] Chain stopped — ${next.id} not marked done.`);
      break;
    }
    execStatus = loadYaml(execPath);
    next = findNextStory(epic, execStatus);
  }

  const elapsed = ((Date.now() - start) / 1000).toFixed(1);
  console.log(`\n[chain] Epic ${epicId}: ran ${count} story/stories in ${elapsed}s`);
  process.exit(0);
}

main().catch((err) => {
  console.error("FATAL:", err);
  process.exit(1);
});
