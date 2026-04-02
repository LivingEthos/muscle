---
description: Run adversarial MUSCLE review that challenges design decisions
agent: build
---

Run MUSCLE pressure review - an adversarial review that challenges design decisions, assumptions, and failure modes.

Usage:
/muscle-pressure [--target <path>] [--focus <areas>] [--intensity <level>] [--options...]

Options:
- --target - Path to review (default: current directory)
- --focus - Focus areas: design, failure, race, auth, data, rollback, reliability (comma-separated)
- --intensity - Review intensity: minimal, moderate, intensive, exhaustive (default: moderate)
- --severity - Minimum severity: critical, high, medium, low (default: low)
- --language - Programming language (auto-detected if not specified)
- --format - Output format: text, json (default: text)
- --shadow - Run in shadow (background) mode

Examples:
/muscle-pressure
/muscle-pressure --target ./src --focus design,failure,race
/muscle-pressure --intensity exhaustive
/muscle-pressure --target ./src --focus auth,data --severity high

Focus Areas:
- design - Challenge design trade-offs and alternative approaches
- failure - Identify failure modes and error handling gaps
- race - Find race conditions and concurrency issues
- auth - Expose authentication and authorization flaws
- data - Detect data loss and corruption risks
- rollback - Question rollback and recovery concerns
- reliability - Assess reliability and error resilience

Intensity Levels:
- minimal - Quick adversarial scan
- moderate - Standard adversarial review
- intensive - Deep adversarial analysis
- exhaustive - Comprehensive attack simulation

Pressure mode doesn't just find bugs - it questions the entire approach. Think like an attacker.
