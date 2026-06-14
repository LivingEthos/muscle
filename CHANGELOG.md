# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-10

Initial public release of MUSCLE (MiniMax Unified Self-Correcting Learning
Engine), a local-first code review and iterative code-generation tool built on
MiniMax M-series models via an Anthropic-compatible API.

### Added

- **Code review subsystem** with multiple modes — `review`, `auto-fix`, `plan`,
  `hybrid`, and `pressure` — combining local static analyzers (Ruff, ESLint,
  TSC, Clippy) with M3-backed semantic review.
- **Self-learning pipeline** that records validated findings into a per-project
  SQLite store (`.muscle/project_memory.db`) and publishes promoted rules into
  the project's `CLAUDE.md`.
- **Host-side context crusher** (`muscle crush` / `muscle expand`) that
  compresses large tool outputs ~50–70% while preserving anomaly lines, with a
  reversible content-addressed store.
- **Delegation cost reporting** (`muscle cost delegation-report`) estimating
  host-model dollars avoided by delegating bulk work to MiniMax M3.
- **Iterative generation loop** (`muscle run`) with budget enforcement, session
  persistence, and resumable runs.
- **Claude Code plugin bundle** with slash commands, hooks, skills, and
  subagents for review, rescue, and pressure-testing workflows.
- **Shell completions** via `muscle completion [bash|zsh|fish]`.

[0.1.0]: https://github.com/LivingEthos/muscle/releases/tag/v0.1.0
