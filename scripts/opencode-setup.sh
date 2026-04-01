#!/usr/bin/env bash
#
# MUSCLE OpenCode Setup Script
#
# This script initializes MUSCLE and prepares it for use with OpenCode.
# Run this once per project after installing MUSCLE.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/scripts/opencode-setup.sh | bash
#   - or -
#   ./scripts/opencode-setup.sh
#

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()  { printf "${CYAN}[INFO]${RESET}  %s\n" "$*"; }
ok()    { printf "${GREEN}[OK]${RESET}    %s\n" "$*"; }
warn()  { printf "${YELLOW}[WARN]${RESET}  %s\n" "$*"; }
error() { printf "${RED}[ERROR]${RESET} %s\n" "$*" >&2; }

usage() {
    cat <<EOF
${BOLD}MUSCLE OpenCode Setup${RESET}

${BOLD}Usage:${RESET}
    $(basename "$0") [OPTIONS]

${BOLD}Options:${RESET}
    --api-key KEY       Set your MiniMax API key (or export MINIMAX_API_KEY before running)
    --project PATH      Project path (default: current directory)
    --global            Install MUSCLE skills globally for all projects
    --help              Show this help message

${BOLD}Examples:${RESET}
    # Set API key interactively
    $(basename "$0")

    # Provide API key directly
    $(basename "$0") --api-key "your-key-here"

    # Initialize in specific project
    $(basename "$0") --project /path/to/project

${BOLD}What this script does:${RESET}
    1. Verifies MUSCLE is installed
    2. Sets up your API key
    3. Runs 'muscle init' to initialize the project
    4. Installs the muscle-review skill for OpenCode (if not present)

EOF
}

# Parse arguments
API_KEY=""
PROJECT_PATH="${PWD}"
GLOBAL_INSTALL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --api-key)
            API_KEY="$2"
            shift 2
            ;;
        --project)
            PROJECT_PATH="$2"
            shift 2
            ;;
        --global)
            GLOBAL_INSTALL=true
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Check if MUSCLE is installed
check_muscle() {
    if command -v muscle &>/dev/null; then
        MUSCLE_VERSION=$(muscle --version 2>&1 || echo "unknown")
        ok "MUSCLE is installed (${MUSCLE_VERSION})"
        return 0
    else
        error "MUSCLE is not installed"
        info "Install with: pip install muscle-cli"
        info "Or: curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/install.sh | bash"
        return 1
    fi
}

# Get API key
get_api_key() {
    if [[ -n "$API_KEY" ]]; then
        return 0
    fi

    # Check environment variable
    if [[ -n "${MINIMAX_API_KEY:-}" ]]; then
        API_KEY="$MINIMAX_API_KEY"
        ok "Using MINIMAX_API_KEY from environment"
        return 0
    fi

    # Check config file
    CONFIG_FILE="${HOME}/.muscle/config.yaml"
    if [[ -f "$CONFIG_FILE" ]] && grep -q "api_key" "$CONFIG_FILE" 2>/dev/null; then
        API_KEY=$(grep "api_key" "$CONFIG_FILE" | head -1 | sed 's/.*api_key:*[[:space:]]*//' | tr -d '"' || echo "")
        if [[ -n "$API_KEY" ]]; then
            ok "Using API key from ${CONFIG_FILE}"
            return 0
        fi
    fi

    # Prompt user
    echo ""
    info "Enter your MiniMax API key (get one at https://platform.minimax.io)"
    read -r -p "API Key: " API_KEY
    echo ""
}

# Set API key in environment and optionally config
configure_api_key() {
    # Export for current session
    export MINIMAX_API_KEY="$API_KEY"

    # Create global config directory
    mkdir -p "${HOME}/.muscle"

    # Create or update config
    CONFIG_FILE="${HOME}/.muscle/config.yaml"
    if [[ -f "$CONFIG_FILE" ]]; then
        if grep -q "api_key" "$CONFIG_FILE" 2>/dev/null; then
            # Update existing
            sed -i.bak "s|api_key:.*|api_key: ${API_KEY}|" "$CONFIG_FILE"
        else
            echo "api_key: ${API_KEY}" >> "$CONFIG_FILE"
        fi
        ok "Updated ${CONFIG_FILE}"
    else
        cat > "$CONFIG_FILE" <<EOF
api_key: ${API_KEY}
base_url: https://api.minimax.io/anthropic
EOF
        ok "Created ${CONFIG_FILE}"
    fi

    ok "API key configured"
}

# Initialize project with MUSCLE
init_project() {
    cd "$PROJECT_PATH"

    info "Initializing MUSCLE in ${PROJECT_PATH}..."

    # Run muscle init (will prompt for settings)
    if muscle init --project "$PROJECT_PATH" 2>&1; then
        ok "Project initialized"
    else
        warn "muscle init had issues (may already be initialized)"
    fi
}

# Install OpenCode skill
install_opencode_skill() {
    SKILL_DIR="${HOME}/.claude/skills/muscle-review"
    SKILL_FILE="${SKILL_DIR}/SKILL.md"

    if [[ -d "$SKILL_DIR" ]]; then
        ok "OpenCode skill already installed at ${SKILL_DIR}"
        return 0
    fi

    info "Installing OpenCode skill for muscle-review..."

    mkdir -p "$SKILL_DIR"

    cat > "$SKILL_FILE" <<'SKILLEOF'
---
name: muscle-review
description: Perform code review using MUSCLE (MiniMax Unified Self-Correcting Learning Engine). Use when reviewing code changes, finding bugs, validating fixes, auditing code quality, or running pressure tests on design decisions. MUSCLE learns project patterns over time and improves its reviews.
user-invocable: true
args:
  - name: target
    description: Path to file or directory to review (defaults to recently changed files)
    required: false
  - name: mode
    description: Review mode - review (find issues), pressure (challenge design), auto-fix (fix automatically), hybrid (safe fixes + plan complex), plan (generate fix plan)
    required: false
  - name: intensity
    description: Review intensity - minimal (quick check), moderate (standard), intensive (critical changes), exhaustive (pre-release audit)
    required: false
---

Run comprehensive code review powered by MUSCLE, a self-learning review system that improves over time by learning project-specific patterns.

## Prerequisites

Ensure MUSCLE is installed and configured:
```bash
# Verify installation
muscle --version

# Set API key (if not already set)
export MINIMAX_API_KEY="your-token-plan-api-key"
```

## Review Modes

### Standard Review (find issues)
Best for: Regular code reviews, bug hunting, pre-commit checks
```bash
muscle review --target <path> --mode review
```

### Pressure Mode (challenge design)
Best for: Critical changes, architectural decisions, complex refactors. Challenges design choices and looks for failure modes.
```bash
muscle review --target <path> --mode pressure --intensity intensive
```

### Auto-Fix Mode
Best for: Quick fixes for auto-fixable issues (linting, formatting, simple bugs)
```bash
muscle review --target <path> --mode auto-fix
```

### Hybrid Mode
Best for: Balancing automation with manual oversight. Fixes safe issues, generates plans for complex ones.
```bash
muscle review --target <path> --mode hybrid
```

### Plan Mode
Best for: Complex changes requiring careful review, generating handoff documentation
```bash
muscle review --target <path> --mode plan --output fix-plan.md
```

## Review Intensity

| Level | When to Use |
|-------|-------------|
| `minimal` | Quick sanity check on small changes |
| `moderate` | Standard review (default) |
| `intensive` | Critical changes, security-sensitive code |
| `exhaustive` | Pre-release audit, compliance review |

## Other MUSCLE Commands

### Single-Shot Validation
Quick check without full review (compiler + linter + tests):
```bash
muscle check --target <path>
```

### Deep-Dive Investigation
Throw a lifeline to M2.7 for complex bug hunting:
```bash
muscle lifeline --target <path> --prompt "investigate the auth module"
```

### Run Code Generation Loop
Generate and evolve code for a task:
```bash
muscle run --task "Build a REST API" --max-iterations 5
```

### Knowledge Base Stats
Check what MUSCLE has learned:
```bash
muscle kb stats
```

## Presenting Results

After running a review, present findings organized by severity:

**Critical/High issues** - Must address before shipping
- File and line number
- What the issue is
- Suggested fix or auto-fix result

**Medium issues** - Should address soon

**Low/Info** - Nice to fix, can be deferred

## Self-Learning System

MUSCLE improves over time:
- Detected patterns stored in `.muscle/` project knowledge base
- Recurring issues (3+ occurrences) trigger skill/agent generation
- Strategy evolution refines review approach
- Memory files (CLAUDE.md, AGENT.md, MEMORY.md) updated automatically

## Notes

- First review in a project runs `muscle init` automatically if needed
- Use `--shadow` flag for background reviews that don't block
- MUSCLE respects `.muscle/` markers in memory files (never overwrites user content outside markers)
- Coverage reports available via `muscle improve report`

## Example Workflows

**Quick review of changed files:**
```
User: review my recent changes
→ muscle review --target ./src --mode review --intensity moderate
```

**Pre-ship pressure test:**
```
User: pressure test the auth module before we ship
→ muscle review --target ./src/auth --mode pressure --intensity exhaustive
```

**Fix and verify:**
```
User: find and fix issues in the api module
→ muscle review --target ./src/api --mode hybrid
→ (present fixes, run muscle check to verify)
```
SKILLEOF

    ok "Installed OpenCode skill at ${SKILL_FILE}"
}

# Main
main() {
    echo ""
    echo -e "${BOLD}MUSCLE OpenCode Setup${RESET}"
    echo ""

    # Step 1: Check MUSCLE installation
    if ! check_muscle; then
        exit 1
    fi

    # Step 2: Get API key
    get_api_key
    if [[ -z "$API_KEY" ]]; then
        error "API key is required"
        exit 1
    fi

    # Step 3: Configure API key
    configure_api_key

    # Step 4: Initialize project
    init_project

    # Step 5: Install OpenCode skill
    install_opencode_skill

    echo ""
    ok "Setup complete!"
    echo ""
    info "Next steps:"
    info "  1. Restart OpenCode to load the muscle-review skill"
    info "  2. Run /muscle-review to start a code review"
    info "  3. Run 'muscle tui' for the terminal interface"
    echo ""
}

main
