#!/usr/bin/env bash
# Setup Verification Script for Linux/macOS
# Verifies that the development environment is correctly configured

set -euo pipefail

echo "🔍 KNX to OpenHAB - Setup Verification (Linux/macOS)"
echo ""

all_checks_passed=true

# Function to display check result
show_check_result() {
    local check_name="$1"
    local passed="$2"
    local message="${3:-}"
    
    if [ "$passed" = "true" ]; then
        echo "✅ $check_name"
        if [ -n "$message" ]; then
            echo "   $message"
        fi
    else
        echo "❌ $check_name"
        if [ -n "$message" ]; then
            echo "   $message"
        fi
        all_checks_passed=false
    fi
}

# Check 1: Python Version
echo "1️⃣  Checking Python..."

if command -v python3 &> /dev/null; then
    PYTHON_CMD=python3
elif command -v python &> /dev/null; then
    PYTHON_CMD=python
else
    show_check_result "Python installation" "false" "Python not found"
    PYTHON_CMD=""
fi

if [ -n "$PYTHON_CMD" ]; then
    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
    IFS='.' read -ra VERSION_PARTS <<< "$PYTHON_VERSION"
    MAJOR=${VERSION_PARTS[0]}
    MINOR=${VERSION_PARTS[1]}
    
    if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 11 ]; then
        show_check_result "Python version" "true" "Python $PYTHON_VERSION"
    else
        show_check_result "Python version" "false" "Python 3.11+ required, found Python $PYTHON_VERSION"
    fi
fi

# Check 2: Virtual Environment
echo ""
echo "2️⃣  Checking virtual environment..."
if [ -d ".venv" ]; then
    show_check_result "Virtual environment exists" "true"
else
    show_check_result "Virtual environment exists" "false" "Run ./scripts/dev-setup.sh if missing"
fi

# Check 3: Dependencies (if venv exists)
if [ -d ".venv" ]; then
    echo ""
    echo "3️⃣  Checking dependencies..."
    
    # Activate venv
    source .venv/bin/activate
    
    required_packages=("flask" "werkzeug" "xknxproject" "lark-parser")
    all_deps_installed=true
    
    for package in "${required_packages[@]}"; do
        if pip show "$package" &> /dev/null; then
            version=$(pip show "$package" | grep "Version:" | awk '{print $2}')
            show_check_result "$package" "true" "v$version"
        else
            show_check_result "$package" "false" "Not installed"
            all_deps_installed=false
        fi
    done
    
    if [ "$all_deps_installed" = "false" ]; then
        echo "   Run: pip install -r requirements.txt"
    fi
fi

# Check 4: Project Structure
echo ""
echo "4️⃣  Checking project structure..."

required_files=(
    "README.md"
    "DEVELOPMENT.md"
    "requirements.txt"
    "config.json"
    "knxproject_to_openhab.py"
    "ets_to_openhab.py"
    "web_ui/backend/app.py"
    "web_ui/backend/jobs.py"
    "web_ui/backend/storage.py"
    "web_ui/backend/config.json"
    "web_ui/templates/index.html"
    "web_ui/static/app.js"
    "web_ui/static/style.css"
)

all_files_exist=true
for file in "${required_files[@]}"; do
    if [ ! -f "$file" ]; then
        show_check_result "$file" "false" "Missing"
        all_files_exist=false
    fi
done

if [ "$all_files_exist" = "true" ]; then
    show_check_result "All required files present" "true"
fi

# Check 5: Runtime Directories
echo ""
echo "5️⃣  Checking runtime directories..."

required_dirs=(
    "var/lib/knx_to_openhab"
    "var/backups/knx_to_openhab"
    "openhab/items"
    "openhab/things"
    "openhab/sitemaps"
)

all_dirs_exist=true
for dir in "${required_dirs[@]}"; do
    if [ ! -d "$dir" ]; then
        show_check_result "$dir" "false" "Missing"
        all_dirs_exist=false
    fi
done

if [ "$all_dirs_exist" = "true" ]; then
    show_check_result "All runtime directories present" "true"
fi

# Summary
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$all_checks_passed" = "true" ]; then
    echo ""
    echo "✨ All checks passed!"
    echo ""
    echo "You're ready to start development:"
    echo "  ./scripts/dev-run.sh"
    echo ""
    exit 0
else
    echo ""
    echo "⚠️  Some checks failed!"
    echo ""
    echo "Please run the setup script:"
    echo "  ./scripts/dev-setup.sh"
    echo ""
    exit 1
fi
