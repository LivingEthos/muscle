#!/usr/bin/env bash
#
# MUSCLE - MiniMax Unified Self-Correcting Learning Engine
# Installer script
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/install.sh | bash
#
# Options (via environment variables):
#   MUSCLE_INSTALL_DIR  - Installation directory (default: ~/.muscle/src)
#   MUSCLE_NO_INIT      - Set to "1" to skip running muscle init
#   MUSCLE_SKIP_UV      - Set to "1" to use pip instead of uv
#   MUSCLE_BRANCH       - Git branch/tag to checkout (default: main)
#   MUSCLE_REPO         - Git repository URL (default: https://github.com/LivingEthos/muscle.git)

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

INSTALL_DIR="${MUSCLE_INSTALL_DIR:-$HOME/.muscle/src}"
NO_INIT="${MUSCLE_NO_INIT:-0}"
SKIP_UV="${MUSCLE_SKIP_UV:-0}"
BRANCH="${MUSCLE_BRANCH:-main}"
REPO="${MUSCLE_REPO:-https://github.com/LivingEthos/muscle.git}"

info()  { printf "${CYAN}[INFO]${RESET}  %s\n" "$*"; }
ok()    { printf "${GREEN}[OK]${RESET}    %s\n" "$*"; }
warn()  { printf "${YELLOW}[WARN]${RESET}  %s\n" "$*"; }
error() { printf "${RED}[ERROR]${RESET} %s\n" "$*" >&2; }

check_cmd() {
    if command -v "$1" &>/dev/null; then
        return 0
    fi
    return 1
}

ensure_git() {
    if ! check_cmd git; then
        error "git is required but not installed."
        info "Install git: https://git-scm.com/downloads"
        exit 1
    fi
}

ensure_python() {
    if check_cmd python3; then
        PYTHON=python3
    elif check_cmd python; then
        PYTHON=python
    else
        error "Python 3.10+ is required but not installed."
        info "Install Python: https://www.python.org/downloads/"
        exit 1
    fi

    py_version=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    py_major=$(echo "$py_version" | cut -d. -f1)
    py_minor=$(echo "$py_version" | cut -d. -f2)

    if [ "$py_major" -lt 3 ] || { [ "$py_major" -eq 3 ] && [ "$py_minor" -lt 10 ]; }; then
        error "Python 3.10+ is required, found Python $py_version"
        exit 1
    fi

    info "Using Python $py_version ($PYTHON)"
}

ensure_uv() {
    if [ "$SKIP_UV" = "1" ]; then
        warn "Skipping uv, will use pip"
        return
    fi

    if check_cmd uv; then
        info "uv found: $(uv --version)"
        return
    fi

    info "Installing uv (Python package manager)..."
    if check_cmd curl; then
        curl -fsSL https://astral.sh/uv/install.sh | sh 2>/dev/null
    elif check_cmd wget; then
        wget -qO- https://astral.sh/uv/install.sh | sh 2>/dev/null
    else
        warn "Cannot install uv automatically (no curl/wget). Falling back to pip."
        SKIP_UV=1
        return
    fi

    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    if check_cmd uv; then
        ok "uv installed: $(uv --version)"
    else
        warn "uv installation may not be on PATH. Falling back to pip."
        SKIP_UV=1
    fi
}

clone_repo() {
    if [ -d "$INSTALL_DIR/.git" ]; then
        info "Updating existing MUSCLE installation at $INSTALL_DIR"
        git -C "$INSTALL_DIR" fetch --quiet origin
        git -C "$INSTALL_DIR" checkout --quiet "$BRANCH"
        git -C "$INSTALL_DIR" pull --quiet origin "$BRANCH" 2>/dev/null || {
            warn "Pull failed, resetting to origin/$BRANCH"
            git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH" --quiet 2>/dev/null || true
        }
    else
        info "Cloning MUSCLE into $INSTALL_DIR..."
        mkdir -p "$(dirname "$INSTALL_DIR")"
        git clone --branch "$BRANCH" --depth 1 --quiet "$REPO" "$INSTALL_DIR"
    fi
    ok "Repository ready at $INSTALL_DIR"
}

install_package() {
    cd "$INSTALL_DIR"

    if [ "$SKIP_UV" = "1" ]; then
        info "Installing MUSCLE with pip..."
        $PYTHON -m pip install -e . --quiet 2>/dev/null || {
            warn "pip install failed, trying with --user..."
            $PYTHON -m pip install -e . --user --quiet
        }
    else
        info "Installing MUSCLE with uv..."
        uv sync --quiet 2>/dev/null || {
            warn "uv sync failed, trying uv pip install..."
            uv pip install -e . --quiet 2>/dev/null
        }
    fi

    ok "Package installed"
}

verify_install() {
    export PATH="$HOME/.local/bin:$PATH"
    MUSCLE_BIN=""

    if check_cmd muscle; then
        ok "MUSCLE CLI available: $(muscle --version 2>/dev/null || echo 'installed')"
        return
    fi

    if [ "$SKIP_UV" != "1" ] && [ -d "$INSTALL_DIR/.venv" ]; then
        MUSCLE_BIN="$INSTALL_DIR/.venv/bin/muscle"
    fi

    if [ -n "$MUSCLE_BIN" ] && [ -x "$MUSCLE_BIN" ]; then
        mkdir -p "$HOME/.local/bin"
        ln -sf "$MUSCLE_BIN" "$HOME/.local/bin/muscle"
        ok "Symlinked muscle to ~/.local/bin/muscle"

        if check_cmd muscle; then
            ok "MUSCLE CLI on PATH: $(muscle --version 2>/dev/null)"
        else
            info "Add to your shell: export PATH=\"$HOME/.local/bin:\$PATH\""
        fi
    else
        warn "Could not find muscle binary. You may need to activate a venv or re-login."
    fi
}

print_plugin_instructions() {
    printf "\n"
    printf "${BOLD}${CYAN}── Claude Code Plugin ──${RESET}\n"
    printf "\n"
    printf "To use MUSCLE as a Claude Code plugin:\n"
    printf "\n"
    printf "  Option A: Load locally\n"
    printf "    claude --plugin-dir %s/tools/muscle/plugin\n" "$INSTALL_DIR"
    printf "\n"
    printf "  Option B: Install from marketplace\n"
    printf "    /plugin marketplace add %s\n" "$REPO"
    printf "    /plugin install muscle@muscle-marketplace\n"
    printf "\n"
    printf "  Then use the slash commands:\n"
    printf "    /muscle:review     Standard review\n"
    printf "    /muscle:pressure   Adversarial review\n"
    printf "    /muscle:rescue     Deep-dive investigation\n"
    printf "    /muscle:status     Check job status\n"
    printf "    /muscle:setup      Configure review gate\n"
    printf "\n"
}

run_init() {
    if [ "$NO_INIT" = "1" ]; then
        return
    fi

    printf "\n"
    info "Running 'muscle init' in current directory..."
    if check_cmd muscle; then
        muscle init --non-interactive 2>/dev/null && ok "MUSCLE initialized" || warn "Init skipped (run 'muscle init' manually)"
    else
        warn "muscle not on PATH. Run 'muscle init' manually after updating your shell."
    fi
}

main() {
    printf "${BOLD}${CYAN}"
    printf "  __  __  __  __  ____  ____ \n"
    printf " |  \\/  |/ _|/ _|| ___||  _ \\ \n"
    printf " | |\\/| | |_| |_ | |__ | |_) |\n"
    printf " | |  | |  _|  _||  __||  _ < \n"
    printf " |_|  |_|_| |_|  |____||_| \\_\\   v0.1.0\n"
    printf "${RESET}\n"
    printf "  MiniMax Unified Self-Correcting Learning Engine\n"
    printf "\n"

    ensure_git
    ensure_python
    ensure_uv
    clone_repo
    install_package
    verify_install
    print_plugin_instructions
    run_init

    printf "\n"
    printf "${BOLD}${GREEN}MUSCLE installed successfully!${RESET}\n"
    printf "\n"
    printf "Set your API key:\n"
    printf "  export MINIMAX_API_KEY=\"your-token-plan-api-key\"\n"
    printf "  export ANTHROPIC_BASE_URL=\"https://api.minimax.io/anthropic\"\n"
    printf "\n"
    printf "Then run:\n"
    printf "  muscle review --target ./src\n"
    printf "\n"
}

main "$@"
