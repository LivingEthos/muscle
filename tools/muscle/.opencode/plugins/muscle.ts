import type { Plugin } from "@opencode-ai/plugin"
import { tool } from "@opencode-ai/plugin"
import { $ } from "bun"
import { existsSync } from "fs"
import { join } from "path"

interface MuscleConfig {
  hooks_enabled: boolean
  review_gate: string
  automation_level: string
  api_key_source: "env" | "opencode" | "ask"
  platform: "opencode" | "claude-code" | "auto"
}

function loadMuscleConfig(worktree: string): MuscleConfig {
  const configPath = join(worktree, ".muscle", "config.yaml")
  const defaultConfig: MuscleConfig = {
    hooks_enabled: true,
    review_gate: "block+fix",
    automation_level: "auto-fix",
    api_key_source: "env",
    platform: "auto",
  }

  if (!existsSync(configPath)) {
    return defaultConfig
  }

  try {
    const content = Bun.file(configPath).text()
    const parsed = JSON.parse(content.replace(/yaml/g, "json"))
    return {
      hooks_enabled: parsed.project?.hooks_enabled ?? true,
      review_gate: parsed.project?.review_gate ?? "block+fix",
      automation_level: parsed.project?.automation_level ?? "auto-fix",
      api_key_source: parsed.project?.api_key_source ?? "env",
      platform: parsed.project?.platform ?? "auto",
    }
  } catch {
    return defaultConfig
  }
}

function getApiKey(): string | null {
  return process.env.MINIMAX_API_KEY || process.env.ANTHROPIC_API_KEY || null
}

async function runMuscle(args: string[]): Promise<string> {
  try {
    const result = await $`muscle ${args}`.text()
    return result
  } catch (e) {
    return `Error running muscle: ${String(e)}`
  }
}

export const MusclePlugin: Plugin = async ({ client, directory, worktree }) => {
  const config = loadMuscleConfig(worktree)

  return {
    "session.idle": async (input: any, output: any) => {
      if (!config.hooks_enabled) return

      const sessionId = input.session?.id
      if (!sessionId) return

      const apiKey = getApiKey()
      if (!apiKey) {
        await client.tui.showToast({
          body: {
            message: "MUSCLE: No API key configured. Run muscle_init to configure.",
            variant: "warning",
          },
        })
        return
      }

      if (config.review_gate === "disabled") return

      const targetPath = directory || worktree
      const mode = config.review_gate === "block+fix" || config.review_gate === "block-all" ? "hybrid" : "review"

      await client.tui.showToast({
        body: {
          message: `MUSCLE: Running post-task review on ${targetPath}...`,
          variant: "info",
        },
      })

      try {
        const result = await $`muscle review --target ${targetPath} --mode ${mode} --severity low --format text`.text()
        if (result.includes("Critical:") || result.includes("High:")) {
          await client.tui.showToast({
            body: { message: "MUSCLE: Issues found! Review recommended.", variant: "warning" },
          })
        } else {
          await client.tui.showToast({
            body: { message: "MUSCLE: Post-task review complete - no issues found.", variant: "success" },
          })
        }
      } catch (error) {
        await client.tui.showToast({
          body: { message: `MUSCLE: Hook error - ${String(error)}`, variant: "error" },
        })
      }
    },

    "session.created": async (input: any, output: any) => {
      const apiKey = getApiKey()
      if (!apiKey && config.api_key_source === "ask") {
        await client.tui.showToast({
          body: { message: "MUSCLE: API key not set. Run muscle_init to configure.", variant: "warning" },
        })
      }
    },

    tool: {
      muscle_review: tool({
        description: "MUSCLE code review - find issues, auto-fix, generate plans. Modes: review (standard), pressure (adversarial), auto-fix, plan (generate plan), hybrid (fix + plan).",
        args: {
          target: tool.schema.string().describe("Target path to review (file or directory)"),
          mode: tool.schema.string().optional().describe("Review mode: review, pressure, auto-fix, plan, hybrid"),
          severity: tool.schema.string().optional().describe("Minimum severity: critical, high, medium, low"),
          language: tool.schema.string().optional().describe("Programming language (auto-detected if not specified)"),
          format: tool.schema.string().optional().describe("Output format: text, json"),
          intensity: tool.schema.string().optional().describe("Review intensity: minimal, moderate, intensive, exhaustive"),
          focus: tool.schema.string().optional().describe("Pressure focus areas: design,failure,race,auth,data,rollback,reliability"),
          shadow: tool.schema.boolean().optional().describe("Run in shadow (background) mode"),
          max_fixes: tool.schema.number().optional().describe("Maximum auto-fixes per round"),
          failsafe: tool.schema.boolean().optional().describe("Stop on critical issues"),
          output: tool.schema.string().optional().describe("Output file for handoff plan (markdown)"),
        },
        async execute(args) {
          const cmd = ["review", "--target", args.target]
          if (args.mode) cmd.push("--mode", args.mode)
          if (args.severity) cmd.push("--severity", args.severity)
          if (args.language) cmd.push("--language", args.language)
          if (args.format) cmd.push("--format", args.format)
          if (args.intensity) cmd.push("--intensity", args.intensity)
          if (args.focus) cmd.push("--focus", args.focus)
          if (args.shadow) cmd.push("--shadow")
          if (args.max_fixes) cmd.push("--max-fixes", String(args.max_fixes))
          if (args.failsafe) cmd.push("--failsafe")
          if (args.output) cmd.push("--output", args.output)
          return await runMuscle(cmd)
        },
      }),

      muscle_pressure: tool({
        description: "MUSCLE adversarial pressure review - challenge design decisions, assumptions, and failure modes. Think like an attacker.",
        args: {
          target: tool.schema.string().describe("Target path to review"),
          focus: tool.schema.string().optional().describe("Focus areas: design, failure, race, auth, data, rollback, reliability"),
          intensity: tool.schema.string().optional().describe("Review intensity: minimal, moderate, intensive, exhaustive"),
          severity: tool.schema.string().optional().describe("Minimum severity: critical, high, medium, low"),
          format: tool.schema.string().optional().describe("Output format: text, json"),
        },
        async execute(args) {
          const cmd = ["review", "--target", args.target, "--mode", "pressure"]
          if (args.focus) cmd.push("--focus", args.focus)
          if (args.intensity) cmd.push("--intensity", args.intensity)
          if (args.severity) cmd.push("--severity", args.severity)
          if (args.format) cmd.push("--format", args.format)
          return await runMuscle(cmd)
        },
      }),

      muscle_rescue: tool({
        description: "MUSCLE deep-dive investigation - root cause analysis, bug hunting, problem solving with M2.7.",
        args: {
          target: tool.schema.string().optional().describe("Target path or file to investigate"),
          prompt: tool.schema.string().describe("Task description for investigation"),
          intensity: tool.schema.string().optional().describe("Investigation intensity: minimal, moderate, intensive, exhaustive"),
          model: tool.schema.string().optional().describe("Model to use (optional)"),
        },
        async execute(args) {
          const cmd = ["lifeline", "--prompt", args.prompt]
          if (args.target) cmd.push("--target", args.target)
          if (args.intensity) cmd.push("--intensity", args.intensity)
          if (args.model) cmd.push("--model", args.model)
          return await runMuscle(cmd)
        },
      }),

      muscle_lifeline: tool({
        description: "MUSCLE lifeline - deep-dive investigation, bug hunting, or problem solving with M2.7. Unlike review which finds issues, lifeline actively solves problems.",
        args: {
          target: tool.schema.string().describe("Path or file to investigate"),
          prompt: tool.schema.string().describe("Task description for investigation"),
          intensity: tool.schema.string().optional().describe("Investigation intensity: minimal, moderate, intensive, exhaustive"),
          model: tool.schema.string().optional().describe("Model to use (optional)"),
        },
        async execute(args) {
          const cmd = ["lifeline", "--target", args.target, "--prompt", args.prompt]
          if (args.intensity) cmd.push("--intensity", args.intensity)
          if (args.model) cmd.push("--model", args.model)
          return await runMuscle(cmd)
        },
      }),

      muscle_check: tool({
        description: "MUSCLE single-shot validation - runs compiler, linter, and test checks once without iteration loop.",
        args: {
          target: tool.schema.string().describe("Target path to validate (file or directory)"),
          language: tool.schema.string().optional().describe("Programming language (auto-detected if not specified)"),
          format: tool.schema.string().optional().describe("Output format: text, json"),
        },
        async execute(args) {
          const cmd = ["check", "--target", args.target]
          if (args.language) cmd.push("--language", args.language)
          if (args.format) cmd.push("--format", args.format)
          return await runMuscle(cmd)
        },
      }),

      muscle_probe: tool({
        description: "MUSCLE shadow job status checker - check status of running and recent background review jobs.",
        args: {
          job_id: tool.schema.string().optional().describe("Specific job ID to check (shows all if not specified)"),
        },
        async execute(args) {
          const cmd = ["probe"]
          if (args.job_id) cmd.push("--job-id", args.job_id)
          return await runMuscle(cmd)
        },
      }),

      muscle_status: tool({
        description: "MUSCLE status - check status of running and recent MUSCLE jobs.",
        args: {
          job_id: tool.schema.string().optional().describe("Specific job ID to check"),
        },
        async execute(args) {
          const cmd = ["probe"]
          if (args.job_id) cmd.push("--job-id", args.job_id)
          return await runMuscle(cmd)
        },
      }),

      muscle_result: tool({
        description: "MUSCLE result - get final diagnosis/results from a completed shadow job.",
        args: {
          job_id: tool.schema.string().optional().describe("Specific job ID to get diagnosis (shows most recent if not specified)"),
        },
        async execute(args) {
          const cmd = ["diagnosis"]
          if (args.job_id) cmd.push("--job-id", args.job_id)
          return await runMuscle(cmd)
        },
      }),

      muscle_diagnosis: tool({
        description: "MUSCLE diagnosis - get final diagnosis/results from a completed shadow job including issues found, top issues, pressure findings, and root cause analysis.",
        args: {
          job_id: tool.schema.string().optional().describe("Specific job ID to get diagnosis (shows most recent if not specified)"),
        },
        async execute(args) {
          const cmd = ["diagnosis"]
          if (args.job_id) cmd.push("--job-id", args.job_id)
          return await runMuscle(cmd)
        },
      }),

      muscle_cancel: tool({
        description: "MUSCLE cancel - cancel a running or pending shadow job.",
        args: {
          job_id: tool.schema.string().optional().describe("Job ID to cancel (shows list if not specified)"),
        },
        async execute(args) {
          const cmd = ["cancel"]
          if (args.job_id) cmd.push(args.job_id)
          return await runMuscle(cmd)
        },
      }),

      muscle_history: tool({
        description: "MUSCLE history - list all past sessions with session ID, task, status, iterations, and timestamp.",
        args: {},
        async execute() {
          return await runMuscle(["history"])
        },
      }),

      muscle_kb_stats: tool({
        description: "MUSCLE knowledge base statistics - show patterns learned, usage counts, and success rates.",
        args: {},
        async execute() {
          return await runMuscle(["kb", "stats"])
        },
      }),

      muscle_kb_add: tool({
        description: "MUSCLE knowledge base - add a strategy/error pattern for future learning.",
        args: {
          pattern: tool.schema.string().describe("Error pattern (what went wrong)"),
          solution: tool.schema.string().describe("Solution strategy (how to fix it)"),
          root_cause: tool.schema.string().optional().describe("Root cause analysis"),
          language: tool.schema.string().optional().describe("Programming language"),
        },
        async execute(args) {
          const cmd = ["kb", "knowledge-add", "-p", args.pattern, "-s", args.solution]
          if (args.root_cause) cmd.push("-r", args.root_cause)
          if (args.language) cmd.push("-l", args.language)
          return await runMuscle(cmd)
        },
      }),

      muscle_kb_export: tool({
        description: "MUSCLE knowledge base - export strategies to JSON file.",
        args: {
          file: tool.schema.string().describe("Output file path"),
        },
        async execute(args) {
          return await runMuscle(["kb", "export", args.file])
        },
      }),

      muscle_kb_import: tool({
        description: "MUSCLE knowledge base - import strategies from JSON file.",
        args: {
          file: tool.schema.string().describe("Input file path"),
        },
        async execute(args) {
          return await runMuscle(["kb", "import", args.file])
        },
      }),

      muscle_settings_show: tool({
        description: "MUSCLE settings - show current configuration including project, platform, API key source, hooks, CLI path, review gate mode, and automation level.",
        args: {},
        async execute() {
          return await runMuscle(["settings", "show"])
        },
      }),

      muscle_settings_api_key: tool({
        description: "MUSCLE settings - set or configure MINIMAX/M2.7 API key.",
        args: {
          key: tool.schema.string().optional().describe("API key to set"),
          source: tool.schema.string().optional().describe("API key source: env, opencode, ask"),
        },
        async execute(args) {
          const cmd = ["settings", "api-key"]
          if (args.key) cmd.push("--key", args.key)
          if (args.source) cmd.push("--source", args.source)
          return await runMuscle(cmd)
        },
      }),

      muscle_settings_hooks: tool({
        description: "MUSCLE settings - configure post-task review hooks.",
        args: {
          enable: tool.schema.boolean().optional().describe("Enable hooks (true) or disable (false)"),
          gate: tool.schema.string().optional().describe("Review gate mode: block+fix, block-all, warn, disabled"),
        },
        async execute(args) {
          const cmd = ["settings", "hooks"]
          if (args.enable !== undefined) cmd.push(args.enable ? "--enable" : "--disable")
          if (args.gate) cmd.push("--gate", args.gate)
          return await runMuscle(cmd)
        },
      }),

      muscle_settings_platform: tool({
        description: "MUSCLE settings - configure platform and CLI settings.",
        args: {
          platform: tool.schema.string().optional().describe("Platform: opencode, claude-code, auto"),
          cli_path: tool.schema.string().optional().describe("Path to muscle CLI"),
        },
        async execute(args) {
          const cmd = ["settings", "platform"]
          if (args.platform) cmd.push("--platform", args.platform)
          if (args.cli_path) cmd.push("--cli-path", args.cli_path)
          return await runMuscle(cmd)
        },
      }),

      muscle_init: tool({
        description: "MUSCLE initialize - initialize MUSCLE for the current project. Creates .muscle/ directory with configuration, knowledge base, and memory files.",
        args: {
          platform: tool.schema.string().optional().describe("Target platform: auto, opencode, claude-code"),
          hooks: tool.schema.boolean().optional().describe("Enable (true) or disable (false) post-task review hooks"),
          non_interactive: tool.schema.boolean().optional().describe("Skip interactive prompts (use defaults)"),
        },
        async execute(args) {
          const cmd = ["init"]
          if (args.platform) cmd.push("--platform", args.platform)
          if (args.hooks === false) cmd.push("--no-hooks")
          if (args.non_interactive) cmd.push("--non-interactive")
          return await runMuscle(cmd)
        },
      }),

      muscle_nightly: tool({
        description: "MUSCLE nightly cron management - enable/disable/run nightly reviews with morning reports.",
        args: {
          action: tool.schema.string().describe("Action: enable, disable, status, run, reports, cleanup"),
          time: tool.schema.string().optional().describe("Run time in HH:MM format (for enable)"),
          target: tool.schema.string().optional().describe("Target path to review (default: current directory)"),
          limit: tool.schema.number().optional().describe("Number of reports to show (for reports)"),
          days: tool.schema.number().optional().describe("Days to keep reports (for cleanup)"),
          force: tool.schema.boolean().optional().describe("Skip confirmation (for cleanup)"),
        },
        async execute(args) {
          const cmd = ["nightly", args.action]
          if (args.time) cmd.push("--time", args.time)
          if (args.target) cmd.push("--target", args.target)
          if (args.limit) cmd.push("--limit", String(args.limit))
          if (args.days) cmd.push("--days", String(args.days))
          if (args.force) cmd.push("--force")
          return await runMuscle(cmd)
        },
      }),

      muscle_improve: tool({
        description: "MUSCLE self-improvement - run self-review, export/import data, generate improved prompts.",
        args: {
          action: tool.schema.string().describe("Action: report, export, import, clear, prompt"),
          file: tool.schema.string().optional().describe("File path for export/import"),
          force: tool.schema.boolean().optional().describe("Skip confirmation (for clear)"),
        },
        async execute(args) {
          const cmd = ["improve", args.action]
          if (args.file) cmd.push(args.file)
          if (args.force) cmd.push("--force")
          return await runMuscle(cmd)
        },
      }),

      muscle_cost_stats: tool({
        description: "MUSCLE cost optimizer - show cache statistics including cached items and total size.",
        args: {
          path: tool.schema.string().optional().describe("Cache directory path"),
        },
        async execute(args) {
          const cmd = ["cost", "stats"]
          if (args.path) cmd.push("--path", args.path)
          return await runMuscle(cmd)
        },
      }),

      muscle_cost_clear: tool({
        description: "MUSCLE cost optimizer - clear cost cache.",
        args: {
          path: tool.schema.string().optional().describe("Cache directory path"),
          force: tool.schema.boolean().optional().describe("Skip confirmation"),
        },
        async execute(args) {
          const cmd = ["cost", "clear"]
          if (args.path) cmd.push("--path", args.path)
          if (args.force) cmd.push("--force")
          return await runMuscle(cmd)
        },
      }),

      muscle_tui: tool({
        description: "MUSCLE TUI - start the Terminal User Interface dashboard.",
        args: {},
        async execute() {
          return await runMuscle(["tui"])
        },
      }),

      muscle_run: tool({
        description: "MUSCLE run - start a new self-improvement generation session with the Generate→Evaluate→Evolve loop.",
        args: {
          task: tool.schema.string().describe("Task description"),
          language: tool.schema.string().optional().describe("Programming language (auto-detected if not specified)"),
          output: tool.schema.string().optional().describe("Output directory (default: current directory)"),
          max_iterations: tool.schema.number().optional().describe("Maximum iterations (default: 20)"),
          timeout: tool.schema.string().optional().describe("Timeout (e.g., 30m, 2h)"),
          budget: tool.schema.string().optional().describe("Budget: unlimited, auto, or token count"),
          eval_mode: tool.schema.string().optional().describe("Evaluation mode: all, sequential, parallel"),
          format: tool.schema.string().optional().describe("Output format: text, json"),
        },
        async execute(args) {
          const cmd = ["run", "--task", args.task]
          if (args.language) cmd.push("--language", args.language)
          if (args.output) cmd.push("--output", args.output)
          if (args.max_iterations) cmd.push("--max-iterations", String(args.max_iterations))
          if (args.timeout) cmd.push("--timeout", args.timeout)
          if (args.budget) cmd.push("--budget", args.budget)
          if (args.eval_mode) cmd.push("--eval-mode", args.eval_mode)
          if (args.format) cmd.push("--format", args.format)
          return await runMuscle(cmd)
        },
      }),

      muscle_abort: tool({
        description: "MUSCLE abort - abort a running session.",
        args: {
          session_id: tool.schema.string().describe("Session ID to abort"),
        },
        async execute(args) {
          return await runMuscle(["abort", args.session_id])
        },
      }),
    },
  }
}

export default MusclePlugin
