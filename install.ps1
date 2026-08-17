# okti installer for Windows (PowerShell)
# Usage: iwr -useb https://raw.githubusercontent.com/oktayelipek/okti/main/install.ps1 -OutFile okti-install.ps1
#        Get-Content okti-install.ps1  # inspect
#        .\okti-install.ps1
#
# The classic `irm ... | iex` pipeline triggers Windows Defender's
# machine-learning heuristics (Trojan:Win32/Commando.A!ml false
# positive). Downloading to a file first, inspecting, then running is
# BOTH safer and less likely to be flagged. If you still see a warning,
# use one of the alternatives at the bottom of this file.

$ErrorActionPreference = "Stop"

function Write-Header {
    Write-Host ""
    Write-Host "  >>>  OKTI  installer  <<<" -ForegroundColor Cyan
    Write-Host "  neural code interface for the terminal" -ForegroundColor Cyan
    Write-Host ""
}

function Get-PythonCommand {
    # Probe version-suffixed binaries first, then fall back.
    $candidates = @("python3.13", "python3.12", "python3.11", "python", "python3")
    foreach ($cmd in $candidates) {
        try {
            $out = & $cmd --version 2>&1
            if ($out -match "Python (\d+)\.(\d+)") {
                $major = [int]$Matches[1]
                $minor = [int]$Matches[2]
                if ($major -ge 3 -and $minor -ge 11) {
                    return $cmd
                }
            }
        } catch {
            continue
        }
    }
    return $null
}

function Install-Okti {
    param([string]$PythonCmd)

    Write-Host "[*] Installing okti..." -ForegroundColor Cyan

    $gitSource = "git+https://github.com/oktayelipek/okti.git@main"
    $sources = @("okti", $gitSource)

    # Prefer pipx (isolated venv) — right tool for user CLIs
    $pipx = Get-Command pipx -ErrorAction SilentlyContinue
    if ($pipx) {
        foreach ($src in $sources) {
            pipx install --force $src 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[+] okti installed via pipx ($src)" -ForegroundColor Green
                return $true
            }
        }
    }

    # Fall back to plain pip / --user
    foreach ($src in $sources) {
        & $PythonCmd -m pip install -U $src 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[+] okti installed via pip ($src)" -ForegroundColor Green
            return $true
        }
        & $PythonCmd -m pip install -U --user $src 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[+] okti installed via pip --user ($src)" -ForegroundColor Green
            return $true
        }
    }

    return $false
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

Write-Header

$pythonCmd = Get-PythonCommand
if (-not $pythonCmd) {
    Write-Host "[!] Python 3.11+ not found on PATH." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Install one of these first, then re-run this script:" -ForegroundColor Yellow
    Write-Host "    winget install Python.Python.3.12" -ForegroundColor Gray
    Write-Host "    winget install Python.Python.3.13" -ForegroundColor Gray
    Write-Host "    OR download from https://www.python.org/downloads/" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  (This script no longer auto-downloads Python — that" -ForegroundColor DarkGray
    Write-Host "   pattern was a Windows Defender ML false-positive trigger.)" -ForegroundColor DarkGray
    exit 1
}

$pythonVersion = & $pythonCmd --version 2>&1
Write-Host "[+] Found: $pythonVersion ($pythonCmd)" -ForegroundColor Green

if (Install-Okti -PythonCmd $pythonCmd) {
    Write-Host ""
    Write-Host "  OK  okti installed" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Quick start:" -ForegroundColor White
    Write-Host "    okti                    # launch TUI" -ForegroundColor Gray
    Write-Host "    okti --help             # show options" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  If 'okti' is not found, add pip's script dir to PATH." -ForegroundColor DarkGray
    Write-Host "  Find it with: $pythonCmd -m site --user-base" -ForegroundColor DarkGray
    Write-Host "  Then append '\Scripts' to that path." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Configure API keys:" -ForegroundColor White
    Write-Host '    $env:OPENAI_API_KEY = "sk-..."' -ForegroundColor Gray
    Write-Host '    $env:ANTHROPIC_API_KEY = "sk-ant-..."' -ForegroundColor Gray
    Write-Host ""
} else {
    Write-Host "[!] Install failed." -ForegroundColor Red
    Write-Host "  Try one of these alternatives:" -ForegroundColor Yellow
    Write-Host "    pipx install git+https://github.com/oktayelipek/okti.git@main" -ForegroundColor Gray
    Write-Host "    $pythonCmd -m pip install --user git+https://github.com/oktayelipek/okti.git@main" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Or clone and install manually:" -ForegroundColor Yellow
    Write-Host "    git clone https://github.com/oktayelipek/okti.git" -ForegroundColor Gray
    Write-Host "    cd okti" -ForegroundColor Gray
    Write-Host "    $pythonCmd -m pip install -e ." -ForegroundColor Gray
    exit 1
}
