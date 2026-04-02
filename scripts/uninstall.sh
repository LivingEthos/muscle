#!/usr/bin/env bash
#
# MUSCLE Uninstall Script
#
# Removes MUSCLE installation, CLI symlinks, and optionally project data.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/scripts/uninstall.sh | bash
#   - or -
#   ./scripts/uninstall.sh
#
# Options:
#   --keep-data     Keep project .muscle/ directories and knowledge bases
#   --keep-config   Keep ~/.muscle/ global config
#   --force         Skip all confirmations
#   --help          Show this help
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

KEEP_DATA=false
KEEP_CONFIG=false
FORCE=false

usage() {
    cat <<EOF
${BOLD}MUSCLE Uninstall${RESET}

Removes MUSCLE installation, CLI binary, and optionally project data.

${BOLD}Usage:${RESET}
    $(basename "$0") [OPTIONS]

${BOLD}Options:${RESET}
    --keep-data     Keep project .muscle/ directories (knowledge bases, memory files)
    --keep-config   Keep ~/.muscle/ global configuration
    --force         Skip all confirmations
    --help          Show this help

${BOLD}What gets removed:${RESET}
    1. MUSCLE source code (~/.muscle/src/)
    2. CLI symlink (~/.local/bin/muscle)
    3. pip/uv package registration
    4. OpenCode skill (~/.claude/skills/muscle-review/)
    5. Global config (~/.muscle/) [unless --keep-config]

${BOLD}What is NOT removed (unless you remove manually):${RESET}
    - Project .muscle/ directories (use --keep-data=false, but default keeps them)
    - Environment variables (MINIMAX_API_KEY, etc.)

EOF
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --keep-data)
            KEEP_DATA=true
            shift
            ;;
        --keep-config)
            KEEP_CONFIG=true
            shift
            ;;
        --force)
            FORCE=true
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

confirm() {
    if [ "$FORCE" = "true" ]; then
        return 0
    fi
    printf "%s [y/N] " "$1"
    read -r answer
    case "$answer" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

remove_package() {
    info "Removing MUSCLE package..."

    # Try uv first
    if command -v uv &>/dev/null; then
        uv pip uninstall muscle 2>/dev/null && ok "Removed via uv" && return 0
    fi

    # Try pip
    if command -v pip3 &>/dev/null; then
        pip3 uninstall muscle -y 2>/dev/null && ok "Removed via pip3" && return 0
    fi
    if command -v pip &>/dev/null; then
        pip uninstall muscle -y 2>/dev/null && ok "Removed via pip" && return 0
    fi

    warn "Could not remove package (may not be pip-installed)"
}

remove_source() {
    local src_dir="${HOME}/.muscle/src"
    if [ -d "$src_dir" ]; then
        info "Removing source directory: $src_dir"
        rm -rf "$src_dir"
        ok "Removed $src_dir"
    else
        info "No source directory found at $src_dir"
    fi
}

remove_symlink() {
    local symlink="${HOME}/.local/bin/muscle"
    if [ -L "$symlink" ] || [ -f "$symlink" ]; then
        info "Removing CLI symlink: $symlink"
        rm -f "$symlink"
        ok "Removed $symlink"
    else
        info "No CLI symlink found at $symlink"
    fi
}

remove_opencode_skill() {
    local skill_dir="${HOME}/.claude/skills/muscle-review"
    if [ -d "$skill_dir" ]; then
        info "Removing OpenCode skill: $skill_dir"
        rm -rf "$skill_dir"
        ok "Removed OpenCode skill"
    else
        info "No OpenCode skill found"
    fi
}

remove_global_config() {
    if [ "$KEEP_CONFIG" = "true" ]; then
        info "Keeping global config (~/.muscle/)"
        return
    fi

    local config_dir="${HOME}/.muscle"
    # Don't remove if src/ still exists (partial uninstall)
    if [ -d "$config_dir/src" ]; then
        warn "Source directory still exists in ~/.muscle/src — skipping config removal"
        return
    fi

    if [ -d "$config_dir" ]; then
        info "Removing global config: $config_dir"
        rm -rf "$config_dir"
        ok "Removed $config_dir"
    fi
}

main() {
    echo ""
    echo -e "${BOLD}MUSCLE Uninstall${RESET}"
    echo ""

    if ! confirm "Are you sure you want to uninstall MUSCLE?"; then
        info "Aborted."
        exit 0
    fi

    echo ""

    remove_package
    remove_symlink
    remove_source
    remove_opencode_skill
    remove_global_config

    echo ""
    ok "MUSCLE has been uninstalled."
    echo ""

    if [ "$KEEP_DATA" = "true" ] || [ "$FORCE" != "true" ]; then
        info "Project .muscle/ directories were kept. Remove them manually if needed:"
        info "  find . -name '.muscle' -type d"
    fi

    info "Remove environment variables from your shell profile if set:"
    info "  MINIMAX_API_KEY, ANTHROPIC_BASE_URL"
    echo ""
}

main
