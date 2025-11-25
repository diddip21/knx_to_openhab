# Development Setup Script for Windows
# Creates virtual environment and installs dependencies

$ErrorActionPreference = "Stop"

Write-Host "KNX to OpenHAB - Development Setup (Windows)" -ForegroundColor Cyan
Write-Host ""

# Check Python version
Write-Host "Checking Python version..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "   Found: $pythonVersion" -ForegroundColor Green
    
    # Extract version number
    if ($pythonVersion -match "Python (\d+)\.(\d+)") {
        $major = [int]$matches[1]
        $minor = [int]$matches[2]
        
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
            Write-Host "   ERROR: Python 3.11+ required, found Python $major.$minor" -ForegroundColor Red
            exit 1
        }
    }
} catch {
    Write-Host "   ERROR: Python not found. Please install Python 3.11+ from https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

# Create virtual environment
Write-Host ""
Write-Host "Creating virtual environment..." -ForegroundColor Yellow
if (Test-Path ".venv") {
    Write-Host "   WARNING: Virtual environment already exists, skipping creation" -ForegroundColor Yellow
} else {
    python -m venv .venv
    Write-Host "   SUCCESS: Virtual environment created" -ForegroundColor Green
}

# Activate virtual environment
Write-Host ""
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

# Upgrade pip
Write-Host ""
Write-Host "Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet

# Install dependencies
Write-Host ""
Write-Host "Installing dependencies from requirements.txt..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet
Write-Host "   SUCCESS: Dependencies installed" -ForegroundColor Green

# Create directories if needed
Write-Host ""
Write-Host "Creating runtime directories..." -ForegroundColor Yellow
$dirs = @(
    "var\lib\knx_to_openhab",
    "var\backups\knx_to_openhab",
    "openhab\items",
    "openhab\things",
    "openhab\sitemaps",
    "openhab\persistence",
    "openhab\rules"
)

foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "   Created: $dir" -ForegroundColor Gray
    }
}
Write-Host "   SUCCESS: Directories ready" -ForegroundColor Green

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Start the development server:" -ForegroundColor White
Write-Host "     .\scripts\dev-run.ps1" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. Open your browser:" -ForegroundColor White
Write-Host "     http://localhost:5000" -ForegroundColor Gray
Write-Host ""
Write-Host "  3. (Optional) Verify setup:" -ForegroundColor White
Write-Host "     .\scripts\verify-setup.ps1" -ForegroundColor Gray
Write-Host ""
