#!/usr/bin/env bash
# okti installer for macOS/Linux
# Usage: curl -fsSL https://raw.githubusercontent.com/oktayelipek/oktigent/main/install.sh | bash

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
    echo -e "${CYAN}  ╔══════════════════════════════════════╗${NC}"
    echo -e "${CYAN}  ║        okti installer             ║${NC}"
    echo -e "${CYAN}  ║  Agentic coding tool for the terminal ║${NC}"
    echo -e "${CYAN}  ╚══════════════════════════════════════╝${NC}"
    echo ""
}

check_python() {
    local cmd=""
    if command -v python3 &>/dev/null; then
        cmd="python3"
    elif command -v python &>/dev/null; then
        cmd="python"
    else
        return 1
    fi
    
    local version=$($cmd --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
    local major=$(echo $version | cut -d. -f1)
    local minor=$(echo $version | cut -d. -f2)
    
    if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
        echo "$cmd"
        return 0
    fi
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
    local python_cmd=$(check_python) || {
        install_python
        python_cmd=$(check_python) || {
            echo -e "${RED}[!] Failed to find/install Python 3.11+${NC}"
            exit 1
        }
    }
    
    echo -e "${GREEN}[+] Found: $($python_cmd --version)${NC}"
    
    echo -e "${CYAN}[*] Installing okti...${NC}"
    
    # Upgrade pip
    $python_cmd -m pip install --upgrade pip --quiet 2>/dev/null || true
    
    # Install okti
    if $python_cmd -m pip install -U okti 2>/dev/null; then
        echo -e "${GREEN}[+] okti installed!${NC}"
    elif $python_cmd -m pip install -U --user okti 2>/dev/null; then
        echo -e "${GREEN}[+] okti installed (user mode)!${NC}"
    else
        echo -e "${RED}[!] pip install failed. Try manually:${NC}"
        echo "    $python_cmd -m pip install okti"
        exit 1
    fi
    
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
