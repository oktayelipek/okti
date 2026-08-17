#!/usr/bin/env bash
# okti installer for macOS/Linux
# Usage: curl -fsSL https://raw.githubusercontent.com/oktayelipek/okti/main/install.sh | bash

set -e

OKTI_VERSION="${OKTI_VERSION:-latest}"
PYTHON_MIN_VERSION="3.11"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

print_header() {
    echo ""
    echo -e "${CYAN}  ▓▒░  OKTI  installer  ░▒▓${NC}"
    echo -e "${CYAN}  neural code interface for the terminal${NC}"
    echo ""
}

check_python() {
    # Try version-suffixed binaries first (python3.13, python3.12, python3.11),
    # then fall back to python3 / python.
    local candidates=(python3.13 python3.12 python3.11 python3 python)
    for cmd in "${candidates[@]}"; do
        if ! command -v "$cmd" &>/dev/null; then
            continue
        fi
        local version major minor
        version=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -n1)
        [ -z "$version" ] && continue
        major=${version%.*}
        minor=${version#*.}
        if [ "$major" -ge 3 ] 2>/dev/null && [ "$minor" -ge 11 ] 2>/dev/null; then
            echo "$cmd"
            return 0
        fi
    done
    return 1
}

install_python() {
    echo -e "${YELLOW}[*] Python $PYTHON_MIN_VERSION+ not found. Installing...${NC}"
    
    local os=$(uname -s)
    
    if [ "$os" = "Darwin" ]; then
        # macOS
        if command -v brew &>/dev/null; then
            brew install python@3.12
        else
            echo -e "${RED}[!] Homebrew not found. Install it first:${NC}"
            echo "    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
            return 1
        fi
    elif [ "$os" = "Linux" ]; then
        # Linux
        if command -v apt-get &>/dev/null; then
            sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv python3-pip
        elif command -v dnf &>/dev/null; then
            sudo dnf install -y python3.12
        elif command -v pacman &>/dev/null; then
            sudo pacman -S python
        else
            echo -e "${RED}[!] Cannot auto-install Python. Please install Python 3.11+ manually.${NC}"
            echo "    https://www.python.org/downloads/"
            return 1
        fi
    fi
}

install_okti() {
    # NOTE: `local var=$(cmd)` masks the exit status of `cmd` because
    # `local` itself always returns 0. Declare first, then assign.
    local python_cmd
    python_cmd=$(check_python)
    if [ -z "$python_cmd" ]; then
        install_python
        python_cmd=$(check_python)
        if [ -z "$python_cmd" ]; then
            echo -e "${RED}[!] Failed to find/install Python 3.11+${NC}"
            exit 1
        fi
    fi

    echo -e "${GREEN}[+] Found: $($python_cmd --version)${NC}"

    echo -e "${CYAN}[*] Installing okti...${NC}"

    # Upgrade pip
    "$python_cmd" -m pip install --upgrade pip --quiet 2>/dev/null || true

    # Install order — prefer isolated tooling over user site, and fall
    # back to the git tree until the PyPI package ships. Both okti and
    # the git URL are attempted at each stage.
    local pip_log
    pip_log=$(mktemp)
    local git_source="git+https://github.com/oktayelipek/okti.git@main"
    local sources=("okti" "$git_source")
    local installed_from=""

    # 1. pipx — the right tool for user-facing CLIs on modern Pythons
    if command -v pipx &>/dev/null; then
        for src in "${sources[@]}"; do
            if pipx install --force "$src" >"$pip_log" 2>&1; then
                installed_from="pipx ($src)"
                break
            fi
        done
    fi

    # 2. plain pip / --user
    if [ -z "$installed_from" ]; then
        for src in "${sources[@]}"; do
            if "$python_cmd" -m pip install -U "$src" >"$pip_log" 2>&1 \
                || "$python_cmd" -m pip install -U --user "$src" >"$pip_log" 2>&1; then
                installed_from="pip ($src)"
                break
            fi
        done
    fi

    # 3. PEP-668 escape hatch: only used if the user opts in
    if [ -z "$installed_from" ] && grep -q "externally-managed-environment" "$pip_log"; then
        echo -e "${YELLOW}[!] Python is externally-managed (PEP 668).${NC}"
        echo -e "${YELLOW}    Retrying with --break-system-packages…${NC}"
        for src in "${sources[@]}"; do
            if "$python_cmd" -m pip install -U --user --break-system-packages "$src" >"$pip_log" 2>&1; then
                installed_from="pip --break-system-packages ($src)"
                break
            fi
        done
    fi

    if [ -z "$installed_from" ]; then
        echo -e "${RED}[!] Install failed. Last output:${NC}"
        tail -n 20 "$pip_log" | sed 's/^/    /'
        echo -e "${RED}[!] Suggested next step:${NC}"
        echo "    pipx install $git_source"
        echo "    OR"
        echo "    $python_cmd -m pip install --user $git_source"
        rm -f "$pip_log"
        exit 1
    fi
    echo -e "${GREEN}[+] okti installed via $installed_from${NC}"
    rm -f "$pip_log"
    
    # Check if okti is in PATH
    if ! command -v okti &>/dev/null; then
        local scripts_dir=$($python_cmd -c "import site; import os; print(os.path.join(os.path.dirname(site.getusersitepackages()), 'bin'))" 2>/dev/null)
        if [ -d "$scripts_dir" ]; then
            echo -e "${YELLOW}[*] Adding to PATH: $scripts_dir${NC}"
            echo "export PATH=\"$scripts_dir:\$PATH\"" >> ~/.bashrc
            echo "export PATH=\"$scripts_dir:\$PATH\"" >> ~/.zshrc 2>/dev/null || true
            export PATH="$scripts_dir:$PATH"
        fi
    fi
}

verify_installation() {
    if command -v okti &>/dev/null; then
        local version=$(okti --version 2>&1 || echo "okti")
        echo ""
        echo -e "${GREEN}  ✅ okti installed successfully!${NC}"
        echo ""
        echo -e "${BOLD}  Quick start:${NC}"
        echo -e "    ${CYAN}okti${NC}                    # Launch TUI"
        echo -e "    ${CYAN}okti --help${NC}             # Show options"
        echo -e "    ${CYAN}okti --yolo${NC}              # Skip permission prompts"
        echo ""
        echo -e "${BOLD}  Configure:${NC}"
        echo -e "    ${CYAN}/provider openai${NC}             # Switch to OpenAI"
        echo -e "    ${CYAN}/models${NC}                      # List available models"
        echo ""
        echo -e "${BOLD}  Set your API key:${NC}"
        echo -e "    ${CYAN}export OPENAI_API_KEY=\"sk-...\"${NC}"
        echo -e "    ${CYAN}export ANTHROPIC_API_KEY=\"sk-ant-...\"${NC}"
        echo ""
    else
        echo -e "${YELLOW}[!] Installation completed but 'okti' not in PATH.${NC}"
        echo "    Try: source ~/.bashrc  OR  source ~/.zshrc"
        echo "    Or run: pip install okti"
    fi
}

# Main
print_header
install_okti
verify_installation
