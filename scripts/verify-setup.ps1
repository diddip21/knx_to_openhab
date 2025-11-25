# Setup Verification Script for Windows
# Verifies that the development environment is correctly configured

$ErrorActionPreference = "Stop"

Write-Host "KNX to OpenHAB - Setup Verification (Windows)" -ForegroundColor Cyan
Write-Host ""

$allChecksPassed = $true

# Function to display check result
function Show-CheckResult {
    param(
        [string]$CheckName,
        [bool]$Passed,
        [string]$Message = ""
    )
    
    if ($Passed) {
        Write-Host "[OK] $CheckName" -ForegroundColor Green
        if ($Message) {
            Write-Host "     $Message" -ForegroundColor Gray
        }
    } else {
        Write-Host "[FAIL] $CheckName" -ForegroundColor Red
        if ($Message) {
            Write-Host "       $Message" -ForegroundColor Yellow
        }
        $script:allChecksPassed = $false
    }
}

# Check 1: Python Version
Write-Host "1. Checking Python..." -ForegroundColor Cyan
try {
    $pythonVersion = python --version 2>&1
    if ($pythonVersion -match "Python (\d+)\.(\d+)\.(\d+)") {
        $major = [int]$matches[1]
        $minor = [int]$matches[2]
        $patch = [int]$matches[3]
        
        if ($major -ge 3 -and $minor -ge 11) {
            Show-CheckResult "Python version" $true "$pythonVersion"
        } else {
            Show-CheckResult "Python version" $false "Python 3.11+ required, found $pythonVersion"
        }
    } else {
        Show-CheckResult "Python version" $false "Could not parse version: $pythonVersion"
    }
} catch {
    Show-CheckResult "Python installation" $false "Python not found"
}

# Check 2: Virtual Environment
Write-Host ""
Write-Host "2. Checking virtual environment..." -ForegroundColor Cyan
$venvExists = Test-Path ".venv"
Show-CheckResult "Virtual environment exists" $venvExists "Run .\scripts\dev-setup.ps1 if missing"

# Check 3: Dependencies (if venv exists)
if ($venvExists) {
    Write-Host ""
    Write-Host "3. Checking dependencies..." -ForegroundColor Cyan
    
    # Activate venv
    & .\.venv\Scripts\Activate.ps1
    
    $requiredPackages = @("flask", "werkzeug", "xknxproject", "lark-parser")
    $allDepsInstalled = $true
    
    foreach ($package in $requiredPackages) {
        $installed = pip show $package 2>$null
        if ($installed) {
            # Extract version
            $version = ($installed | Select-String "Version:").ToString().Split(":")[1].Trim()
            Show-CheckResult "$package" $true "v$version"
        } else {
            Show-CheckResult "$package" $false "Not installed"
            $allDepsInstalled = $false
        }
    }
    
    if (-not $allDepsInstalled) {
        Write-Host "   Run: pip install -r requirements.txt" -ForegroundColor Yellow
    }
}

# Check 4: Project Structure
Write-Host ""
Write-Host "4. Checking project structure..." -ForegroundColor Cyan

$requiredFiles = @(
    "README.md",
    "DEVELOPMENT.md",
    "requirements.txt",
    "config.json",
    "knxproject_to_openhab.py",
    "ets_to_openhab.py",
    "web_ui\backend\app.py",
    "web_ui\backend\jobs.py",
    "web_ui\backend\storage.py",
    "web_ui\backend\config.json",
    "web_ui\templates\index.html",
    "web_ui\static\app.js",
    "web_ui\static\style.css"
)

$allFilesExist = $true
foreach ($file in $requiredFiles) {
    $exists = Test-Path $file
    if (-not $exists) {
        Show-CheckResult $file $false "Missing"
        $allFilesExist = $false
    }
}

if ($allFilesExist) {
    Show-CheckResult "All required files present" $true
}

# Check 5: Runtime Directories
Write-Host ""
Write-Host "5. Checking runtime directories..." -ForegroundColor Cyan

$requiredDirs = @(
    "var\lib\knx_to_openhab",
    "var\backups\knx_to_openhab",
    "openhab\items",
    "openhab\things",
    "openhab\sitemaps"
)

$allDirsExist = $true
foreach ($dir in $requiredDirs) {
    $exists = Test-Path $dir
    if (-not $exists) {
        Show-CheckResult $dir $false "Missing"
        $allDirsExist = $false
    }
}

if ($allDirsExist) {
    Show-CheckResult "All runtime directories present" $true
}

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor Gray

if ($allChecksPassed) {
    Write-Host ""
    Write-Host "All checks passed!" -ForegroundColor Green
    Write-Host ""
    Write-Host "You're ready to start development:" -ForegroundColor Cyan
    Write-Host "  .\scripts\dev-run.ps1" -ForegroundColor White
    Write-Host ""
    exit 0
} else {
    Write-Host ""
    Write-Host "Some checks failed!" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Please run the setup script:" -ForegroundColor Cyan
    Write-Host "  .\scripts\dev-setup.ps1" -ForegroundColor White
    Write-Host ""
    exit 1
}
