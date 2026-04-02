import { tool } from "@opencode-ai/plugin"
import { $ } from "bun"

export const muscle_review = tool({
  description: "MUSCLE code review - find issues, auto-fix, generate plans",
  args: {
    target: tool.schema.string().describe("Target path to review (file or directory)"),
    mode: tool.schema.string().optional().describe("Review mode: review, pressure, auto-fix, plan, hybrid (default: review)"),
    severity: tool.schema.string().optional().describe("Minimum severity: critical, high, medium, low (default: low)"),
    language: tool.schema.string().optional().describe("Programming language (auto-detected if not specified)"),
    format: tool.schema.string().optional().describe("Output format: text, json (default: text)"),
    intensity: tool.schema.string().optional().describe("Review intensity: minimal, moderate, intensive, exhaustive"),
    focus: tool.schema.string().optional().describe("Pressure focus areas: design,failure,race,auth,data,rollback,reliability"),
    shadow: tool.schema.boolean().optional().describe("Run in shadow (background) mode"),
  },
  async execute(args, context) {
    const cmd = ["muscle", "review", "--target", args.target]
    if (args.mode) cmd.push("--mode", args.mode)
    if (args.severity) cmd.push("--severity", args.severity)
    if (args.language) cmd.push("--language", args.language)
    if (args.format) cmd.push("--format", args.format)
    if (args.intensity) cmd.push("--intensity", args.intensity)
    if (args.focus) cmd.push("--focus", args.focus)
    if (args.shadow) cmd.push("--shadow")

    const result = await $`${cmd}`.text()
    return result
  }
})

export const muscle_pressure = tool({
  description: "MUSCLE adversarial pressure review - challenge design decisions",
  args: {
    target: tool.schema.string().describe("Target path to review"),
    focus: tool.schema.string().optional().describe("Focus areas: design, failure, race, auth, data, rollback, reliability (comma-separated)"),
    intensity: tool.schema.string().optional().describe("Review intensity: minimal, moderate, intensive, exhaustive (default: moderate)"),
    format: tool.schema.string().optional().describe("Output format: text, json"),
  },
  async execute(args, context) {
    const cmd = ["muscle", "review", "--target", args.target, "--mode", "pressure"]
    if (args.focus) cmd.push("--focus", args.focus)
    if (args.intensity) cmd.push("--intensity", args.intensity)
    if (args.format) cmd.push("--format", args.format)

    const result = await $`${cmd}`.text()
    return result
  }
})

export const muscle_rescue = tool({
  description: "MUSCLE deep-dive investigation and rescue",
  args: {
    target: tool.schema.string().optional().describe("Target path or file to investigate"),
    prompt: tool.schema.string().describe("Task description for investigation"),
    intensity: tool.schema.string().optional().describe("Investigation intensity: minimal, moderate, intensive, exhaustive"),
    model: tool.schema.string().optional().describe("Model to use (optional)"),
  },
  async execute(args, context) {
    const cmd = ["muscle", "lifeline"]
    if (args.target) cmd.push("--target", args.target)
    cmd.push("--prompt", args.prompt)
    if (args.intensity) cmd.push("--intensity", args.intensity)
    if (args.model) cmd.push("--model", args.model)

    const result = await $`${cmd}`.text()
    return result
  }
})

export const muscle_status = tool({
  description: "MUSCLE shadow job status checker",
  args: {
    job_id: tool.schema.string().optional().describe("Specific job ID to check (shows all if not specified)"),
  },
  async execute(args, context) {
    const cmd = ["muscle", "probe"]
    if (args.job_id) cmd.push("--job-id", args.job_id)

    const result = await $`${cmd}`.text()
    return result
  }
})

export const muscle_result = tool({
  description: "MUSCLE shadow job diagnosis/results",
  args: {
    job_id: tool.schema.string().optional().describe("Specific job ID to get diagnosis (shows most recent if not specified)"),
  },
  async execute(args, context) {
    const cmd = ["muscle", "diagnosis"]
    if (args.job_id) cmd.push("--job-id", args.job_id)

    const result = await $`${cmd}`.text()
    return result
  }
})

export const muscle_cancel = tool({
  description: "MUSCLE shadow job cancellation",
  args: {
    job_id: tool.schema.string().describe("Job ID to cancel"),
  },
  async execute(args, context) {
    const cmd = ["muscle", "abort", args.job_id]
    const result = await $`${cmd}`.text()
    return result
  }
})

export const muscle_check = tool({
  description: "MUSCLE single-shot validation (compiler, linter, tests)",
  args: {
    target: tool.schema.string().describe("Target path to validate (file or directory)"),
    language: tool.schema.string().optional().describe("Programming language (auto-detected if not specified)"),
    format: tool.schema.string().optional().describe("Output format: text, json"),
  },
  async execute(args, context) {
    const cmd = ["muscle", "check", "--target", args.target]
    if (args.language) cmd.push("--language", args.language)
    if (args.format) cmd.push("--format", args.format)

    const result = await $`${cmd}`.text()
    return result
  }
})

export const muscle_setup = tool({
  description: "MUSCLE setup and configuration",
  args: {
    api_key: tool.schema.string().optional().describe("Set MINIMAX/M2.7 API key"),
    hooks: tool.schema.string().optional().describe("Enable/disable hooks: enabled, disabled"),
    platform: tool.schema.string().optional().describe("Platform: opencode, claude-code, auto"),
    non_interactive: tool.schema.boolean().optional().describe("Skip interactive prompts (use defaults)"),
  },
  async execute(args, context) {
    const cmd = ["muscle", "init"]
    if (args.api_key) {
      // API key should be set via environment, not passed as arg
      const shellCmd = `export MINIMAX_API_KEY='${args.api_key}' && muscle init`
      const result = await $`${shellCmd}`.text()
      return result
    }
    if (args.hooks || args.platform || args.non_interactive) {
      const shellCmd = ["muscle", "init", "--non-interactive"]
      const result = await $`${shellCmd}`.text()
      return result
    }
    
    const result = await $`muscle init`.text()
    return result
  }
})

export const muscle_nightly = tool({
  description: "MUSCLE nightly cron management",
  args: {
    action: tool.schema.string().describe("Action: enable, disable, status, run"),
    time: tool.schema.string().optional().describe("Run time in HH:MM format (for enable)"),
    target: tool.schema.string().optional().describe("Target path to review (default: current directory)"),
  },
  async execute(args, context) {
    const cmd = ["muscle", "nightly", args.action]
    if (args.time) cmd.push("--time", args.time)
    if (args.target) cmd.push("--target", args.target)

    const result = await $`${cmd}`.text()
    return result
  }
})

export const muscle_history = tool({
  description: "MUSCLE session history - list all past sessions",
  args: {},
  async execute(args, context) {
    const result = await $`muscle history`.text()
    return result
  }
})

export const muscle_kb_stats = tool({
  description: "MUSCLE knowledge base statistics",
  args: {
    path: tool.schema.string().optional().describe("Knowledge base path (optional)"),
  },
  async execute(args, context) {
    const cmd = ["muscle", "kb", "stats"]
    if (args.path) cmd.push("--path", args.path)

    const result = await $`${cmd}`.text()
    return result
  }
})

export const muscle_kb_add = tool({
  description: "MUSCLE knowledge base - add a strategy",
  args: {
    pattern: tool.schema.string().describe("Error pattern (what went wrong)"),
    solution: tool.schema.string().describe("Solution strategy (how to fix it)"),
    root_cause: tool.schema.string().optional().describe("Root cause analysis (optional)"),
    language: tool.schema.string().optional().describe("Programming language (optional)"),
  },
  async execute(args, context) {
    const cmd = ["muscle", "kb", "knowledge-add", "-p", args.pattern, "-s", args.solution]
    if (args.root_cause) cmd.push("-r", args.root_cause)
    if (args.language) cmd.push("-l", args.language)

    const result = await $`${cmd}`.text()
    return result
  }
})

export const muscle_settings_show = tool({
  description: "MUSCLE settings - show current configuration",
  args: {},
  async execute(args, context) {
    const result = await $`muscle settings show`.text()
    return result
  }
})

export const muscle_settings_api_key = tool({
  description: "MUSCLE settings - set or configure API key",
  args: {
    key: tool.schema.string().optional().describe("API key to set"),
    source: tool.schema.string().optional().describe("API key source: env, opencode, ask"),
  },
  async execute(args, context) {
    if (args.key) {
      const shellCmd = `export MINIMAX_API_KEY='${args.key}' && muscle settings api-key --key '${args.key}'`
      const result = await $`${shellCmd}`.text()
      return result
    }
    if (args.source) {
      const result = await $`muscle settings api-key --source ${args.source}`.text()
      return result
    }
    const result = await $`muscle settings api-key`.text()
    return result
  }
})

export const muscle_settings_hooks = tool({
  description: "MUSCLE settings - configure hooks",
  args: {
    enable: tool.schema.boolean().optional().describe("Enable hooks (true to enable, false to disable)"),
    gate: tool.schema.string().optional().describe("Review gate mode: block+fix, block-all, warn, disabled"),
  },
  async execute(args, context) {
    const cmd = ["muscle", "settings", "hooks"]
    if (args.enable !== undefined) {
      cmd.push(args.enable ? "--enable" : "--disable")
    }
    if (args.gate) cmd.push("--gate", args.gate)

    const result = await $`${cmd}`.text()
    return result
  }
})

export const muscle_settings_platform = tool({
  description: "MUSCLE settings - configure platform",
  args: {
    platform: tool.schema.string().optional().describe("Platform: opencode, claude-code, auto"),
    cli_path: tool.schema.string().optional().describe("Path to muscle CLI"),
  },
  async execute(args, context) {
    const cmd = ["muscle", "settings", "platform"]
    if (args.platform) cmd.push("--platform", args.platform)
    if (args.cli_path) cmd.push("--cli-path", args.cli_path)

    const result = await $`${cmd}`.text()
    return result
  }
})
