# Development Server Start Script for Windows
# Starts Flask development server with debug mode

$ErrorActionPreference = "Stop"

Write-Host "Starting KNX to OpenHAB Web UI (Development Server)" -ForegroundColor Cyan
Write-Host ""

# Check if venv exists
if (-not (Test-Path ".venv")) {
    Write-Host "ERROR: Virtual environment not found!" -ForegroundColor Red
    Write-Host "   Please run: .\scripts\dev-setup.ps1" -ForegroundColor Yellow
    exit 1
}

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

# Start Flask development server
Write-Host ""
Write-Host "Starting Flask development server..." -ForegroundColor Green
Write-Host "   URL: http://localhost:5000" -ForegroundColor Cyan
Write-Host "   Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host ""

# Set Flask environment variables and start
$env:FLASK_APP = "web_ui.backend.app:app"
$env:FLASK_ENV = "development"

flask run --host 127.0.0.1 --port 5000 --debug
