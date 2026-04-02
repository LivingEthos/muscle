import type { Plugin } from "@opencode-ai/plugin"
import { $ } from "bun"
import { readFileSync, existsSync } from "fs"
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
    const content = readFileSync(configPath, "utf-8")
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

export const MuscleIntegrationPlugin: Plugin = async ({ client, $, directory, worktree }) => {
  const config = loadMuscleConfig(worktree)

  return {
    "session.idle": async (input, output) => {
      if (!config.hooks_enabled) {
        return
      }

      const sessionId = input.session?.id
      if (!sessionId) {
        return
      }

      const apiKey = getApiKey()
      if (!apiKey) {
        await client.tui.showToast({
          body: {
            message: "MUSCLE: No API key configured. Run /muscle-setup to configure.",
            variant: "warning",
          },
        })
        return
      }

      const reviewGate = config.review_gate
      if (reviewGate === "disabled") {
        return
      }

      const targetPath = directory || worktree

      let mode = "review"
      if (reviewGate === "block+fix" || reviewGate === "block-all") {
        mode = "hybrid"
      }

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
            body: {
              message: "MUSCLE: Issues found! Review recommended.",
              variant: "warning",
            },
          })
        } else {
          await client.tui.showToast({
            body: {
              message: "MUSCLE: Post-task review complete - no issues found.",
              variant: "success",
            },
          })
        }
      } catch (error) {
        await client.tui.showToast({
          body: {
            message: `MUSCLE: Hook error - ${String(error)}`,
            variant: "error",
          },
        })
      }
    },

    "session.created": async (input, output) => {
      const apiKey = getApiKey()
      if (!apiKey && config.api_key_source === "ask") {
        await client.tui.showToast({
          body: {
            message: "MUSCLE: API key not set. Run /muscle-setup to configure.",
            variant: "warning",
          },
        })
      }
    },

    "tool.execute.before": async (input, output) => {
      if (!config.hooks_enabled) {
        return
      }

      const reviewGate = config.review_gate
      if (reviewGate !== "block+fix" && reviewGate !== "block-all") {
        return
      }

      if (input.tool === "edit" || input.tool === "write") {
        // File modification detected - could trigger immediate review
        // For now, we just track and review at session end
      }
    },

    tool: {
      muscle_review: async (args: any, context: any) => {
        const cmd = ["muscle", "review", "--target", args.target]
        if (args.mode) cmd.push("--mode", args.mode)
        if (args.severity) cmd.push("--severity", args.severity)
        if (args.format) cmd.push("--format", args.format)

        const result = await $`${cmd}`.text()
        return result
      },
    },
  }
}

export default MuscleIntegrationPlugin
