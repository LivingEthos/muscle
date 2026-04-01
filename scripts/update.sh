#!/usr/bin/env bash
#
# MUSCLE Update Script
#
# Updates MUSCLE to the latest version. Works regardless of installation method.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/scripts/update.sh | bash
#   - or -
#   ./scripts/update.sh
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
${BOLD}MUSCLE Update${RESET}

Updates MUSCLE to the latest version from GitHub.

${BOLD}Usage:${RESET}
    $(basename "$0") [OPTIONS]

${BOLD}Options:${RESET}
    --check         Check for updates without installing
    --version VER   Install specific version/tag
    --help          Show this help

${BOLD}Examples:${RESET}
    # Update to latest
    $(basename "$0")

    # Check what version is available
    $(basename "$0") --check

    # Install specific version
    $(basename "$0") --version v0.1.12

EOF
}

# Get current version
get_current_version() {
    if command -v muscle &>/dev/null; then
        muscle --version 2>&1 | grep -oP 'version \K[0-9.]+' || echo "unknown"
    else
        echo "not installed"
    fi
}

# Get latest version from GitHub
get_latest_version() {
    curl -fsSL --silent "https://api.github.com/repos/LivingEthos/muscle/releases/latest" 2>/dev/null | \
        grep '"tag_name"' | sed 's/.*"tag_name": "v*\([^"]*\)".*/\1/' || \
        echo "unknown"
}

# Check for updates
check_updates() {
    CURRENT=$(get_current_version)
    LATEST=$(get_latest_version)

    if [[ "$CURRENT" == "not installed" ]]; then
        info "MUSCLE is not installed"
        info "Install with: curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/install.sh | bash"
        return 0
    fi

    info "Current version:  ${CURRENT}"
    info "Latest version:   ${LATEST}"

    if [[ "$CURRENT" == "$LATEST" ]]; then
        ok "MUSCLE is up to date!"
    elif [[ "$LATEST" != "unknown" ]]; then
        warn "Update available!"
        echo ""
        info "Run 'curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/scripts/update.sh | bash' to update"
    fi
}

# Update MUSCLE
do_update() {
    local VERSION="${1:-}"

    info "Updating MUSCLE..."

    # Detect installation method and update accordingly
    local INSTALL_DIR=""

    # Check if installed via curl installer
    if [[ -d "${HOME}/.muscle/src" ]]; then
        INSTALL_DIR="${HOME}/.muscle/src"

        cd "$INSTALL_DIR"

        # Check for uncommitted changes
        if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
            warn "Local changes detected in ${INSTALL_DIR}"
            info "Stashing changes..."
            git stash
            local STASHED=true
        fi

        # Pull latest
        info "Pulling latest changes..."
        if [[ -n "$VERSION" ]]; then
            git fetch --tags
            git checkout "v${VERSION}" || git checkout "$VERSION" || git checkout "tags/${VERSION}"
        else
            git pull --rebase origin main
        fi

        # Restore stashed changes
        if [[ "${STASHED:-false}" == "true" ]]; then
            info "Restoring local changes..."
            git stash pop || true
        fi

        # Reinstall
        info "Reinstalling..."
        if command -v uv &>/dev/null; then
            uv pip install -e . --reinstall 2>/dev/null || uv sync 2>/dev/null || uv pip install -e .
        else
            pip install -e . --quiet
        fi

        ok "Updated MUSCLE"
        muscle --version

    # Check if installed via pip
    elif command -v pip &>/dev/null && pip show muscle-cli &>/dev/null; then
        info "Detected pip installation"
        if [[ -n "$VERSION" ]]; then
            pip install "muscle-cli==${VERSION}" --quiet
        else
            pip install muscle-cli --upgrade --quiet
        fi
        ok "Updated MUSCLE via pip"
        muscle --version

    # Check if installed via npm
    elif command -v npm &>/dev/null && npm list -g muscle-cli &>/dev/null; then
        info "Detected npm installation"
        if [[ -n "$VERSION" ]]; then
            npm install -g "muscle-cli@${VERSION}"
        else
            npm update -g muscle-cli
        fi
        ok "Updated MUSCLE via npm"
        muscle --version

    else
        error "Could not detect MUSCLE installation method"
        info "Installing fresh from GitHub..."
        curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/install.sh | bash
        return $?
    fi

    # Update OpenCode skill if it exists
    update_opencode_skill
}

# Update OpenCode skill
update_opencode_skill() {
    local SKILL_FILE="${HOME}/.claude/skills/muscle-review/SKILL.md"

    if [[ -f "$SKILL_FILE" ]]; then
        info "Updating OpenCode skill..."

        # The skill is embedded in the setup script, so we re-fetch it
        curl -fsSL "https://raw.githubusercontent.com/LivingEthos/muscle/main/scripts/opencode-setup.sh" 2>/dev/null | \
            sed -n '/^cat >.*SKILL.md.*<<.*SKILLEOF$/,/^SKILLEOF$/p' | \
            sed '1d;$d' > "$SKILL_FILE"

        ok "Updated OpenCode skill"
    fi
}

# Main
main() {
    local CHECK_ONLY=false
    local VERSION=""

    while [[ $# -gt 0 ]]; do
        case $1 in
            --check)
                CHECK_ONLY=true
                shift
                ;;
            --version)
                VERSION="$2"
                shift 2
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

    echo ""
    echo -e "${BOLD}MUSCLE Update${RESET}"
    echo ""

    if [[ "$CHECK_ONLY" == "true" ]]; then
        check_updates
    elif [[ -n "$VERSION" ]]; then
        do_update "$VERSION"
    else
        do_update
    fi
}

main "$@"
