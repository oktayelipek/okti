# oktigent installer for Windows
# Usage: powershell -c "irm https://raw.githubusercontent.com/oktayelipek/oktigent/main/install.ps1 | iex"
# Or:    oktigent

$ErrorActionPreference = "Stop"

$OKTIGENT_VERSION = "latest"
$PYTHON_MIN_VERSION = "3.11"
$INSTALL_DIR = "$env:LOCALAPPDATA\oktigent"
$BIN_DIR = "$env:LOCALAPPDATA\oktigent\bin"

function Write-Header {
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "  ║        oktigent installer             ║" -ForegroundColor Cyan
    Write-Host "  ║  Agentic coding tool for the terminal ║" -ForegroundColor Cyan
    Write-Host "  ╚══════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Test-PythonVersion {
    try {
        $pythonVersion = python --version 2>&1 | Select-Object -First 1
        if ($pythonVersion -match "Python (\d+)\.(\d+)") {
            $major = [int]$matches[1]
            $minor = [int]$matches[2]
            if ($major -ge 3 -and $minor -ge 11) {
                return $true
            }
        }
    } catch {}
    return $false
}

function Install-Python {
    Write-Host "[*] Python $PYTHON_MIN_VERSION+ not found. Installing..." -ForegroundColor Yellow
    
    # Try winget first
    try {
        winget install Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        return $true
    } catch {
        Write-Host "[!] winget install failed, trying pip..." -ForegroundColor Yellow
    }
    
    # Try pyenv-win or direct download
    try {
        $url = "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe"
        $installer = "$env:TEMP\python-installer.exe"
        Invoke-WebRequest -Uri $url -OutFile $installer
        Start-Process -FilePath $installer -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1" -Wait
        Remove-Item $installer -ErrorAction SilentlyContinue
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        return $true
    } catch {
        Write-Host "[!] Failed to install Python. Please install Python 3.11+ manually." -ForegroundColor Red
        Write-Host "    https://www.python.org/downloads/" -ForegroundColor Gray
        return $false
    }
}

function Install-Oktigent {
    Write-Host "[*] Installing oktigent..." -ForegroundColor Cyan
    
    # Ensure pip is available
    try {
        python -m pip --version | Out-Null
    } catch {
        Write-Host "[*] Upgrading pip..." -ForegroundColor Yellow
        python -m pip install --upgrade pip 2>&1 | Out-Null
    }
    
    # Install oktigent
    $result = python -m pip install -U oktigent 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[!] pip install failed. Trying with --user flag..." -ForegroundColor Yellow
        python -m pip install -U --user oktigent 2>&1
    }
    
    return $LASTEXITCODE -eq 0
}

function Add-ToPath {
    $scriptsDir = python -c "import site; print(site.getusersitepackages())" 2>$null
    if ($scriptsDir) {
        $scriptsDir = $scriptsDir -replace "site-packages", "Scripts"
        $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
        if ($currentPath -notlike "*$scriptsDir*") {
            [Environment]::SetEnvironmentVariable("Path", "$currentPath;$scriptsDir", "User")
            $env:Path += ";$scriptsDir"
            Write-Host "[+] Added to PATH: $scriptsDir" -ForegroundColor Green
        }
    }
}

function Test-Installation {
    try {
        $version = oktigent --version 2>&1
        if ($version -match "oktigent") {
            return $true
        }
    } catch {}
    return $false
}

# Main
Write-Header

# Check/install Python
if (-not (Test-PythonVersion)) {
    if (-not (Install-Python)) {
        exit 1
    }
}

$pythonVersion = python --version 2>&1
Write-Host "[+] Found: $pythonVersion" -ForegroundColor Green

# Install oktigent
if (Install-Oktigent) {
    Add-ToPath
    
    if (Test-Installation) {
        Write-Host ""
        Write-Host "  ✅ oktigent installed successfully!" -ForegroundColor Green
        Write-Host ""
        Write-Host "  Quick start:" -ForegroundColor White
        Write-Host "    oktigent                    # Launch TUI" -ForegroundColor Gray
        Write-Host "    oktigent --help             # Show options" -ForegroundColor Gray
        Write-Host "    oktigent --yolo              # Skip permission prompts" -ForegroundColor Gray
        Write-Host ""
        Write-Host "  Configure:" -ForegroundColor White
        Write-Host "    /provider openai             # Switch to OpenAI" -ForegroundColor Gray
        Write-Host "    /models                      # List available models" -ForegroundColor Gray
        Write-Host ""
        Write-Host "  Set your API key:" -ForegroundColor White
        Write-Host '    $env:OPENAI_API_KEY = "sk-..."' -ForegroundColor Gray
        Write-Host '    $env:ANTHROPIC_API_KEY = "sk-ant-..."' -ForegroundColor Gray
        Write-Host ""
    } else {
        Write-Host "[!] Installation completed but 'oktigent' command not found." -ForegroundColor Yellow
        Write-Host "    Try restarting your terminal or running: pip install oktigent" -ForegroundColor Gray
    }
} else {
    Write-Host "[!] Installation failed." -ForegroundColor Red
    Write-Host "    Try manually: pip install oktigent" -ForegroundColor Gray
    exit 1
}
