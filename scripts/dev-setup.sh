#!/usr/bin/env bash
# Development Setup Script for Linux/macOS
# Creates virtual environment and installs dependencies

set -euo pipefail

echo "🚀 KNX to OpenHAB - Development Setup (Linux/macOS)"
echo ""

# Check Python version
echo "📋 Checking Python version..."
if command -v python3 &> /dev/null; then
    PYTHON_CMD=python3
elif command -v python &> /dev/null; then
    PYTHON_CMD=python
else
    echo "   ❌ Python not found. Please install Python 3.11+"
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
echo "   Found: Python $PYTHON_VERSION"

# Extract major and minor version
IFS='.' read -ra VERSION_PARTS <<< "$PYTHON_VERSION"
MAJOR=${VERSION_PARTS[0]}
MINOR=${VERSION_PARTS[1]}

if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]); then
    echo "   ❌ Python 3.11+ required, found Python $MAJOR.$MINOR"
    exit 1
fi

# Create virtual environment
echo ""
echo "📦 Creating virtual environment..."
if [ -d ".venv" ]; then
    echo "   ⚠️  Virtual environment already exists, skipping creation"
else
    $PYTHON_CMD -m venv .venv
    echo "   ✅ Virtual environment created"
fi

# Activate virtual environment
echo ""
echo "🔧 Activating virtual environment..."
source .venv/bin/activate

# Upgrade pip
echo ""
echo "📥 Upgrading pip..."
python -m pip install --upgrade pip --quiet

# Install dependencies
echo ""
echo "📥 Installing dependencies from requirements.txt..."
pip install -r requirements.txt --quiet
echo "   ✅ Dependencies installed"

# Create directories if needed
echo ""
echo "📁 Creating runtime directories..."
DIRS=(
    "var/lib/knx_to_openhab"
    "var/backups/knx_to_openhab"
    "openhab/items"
    "openhab/things"
    "openhab/sitemaps"
    "openhab/persistence"
    "openhab/rules"
)

for dir in "${DIRS[@]}"; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        echo "   Created: $dir"
    fi
done
echo "   ✅ Directories ready"

# Summary
echo ""
echo "✨ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Start the development server:"
echo "     ./scripts/dev-run.sh"
echo ""
echo "  2. Open your browser:"
echo "     http://localhost:5000"
echo ""
echo "  3. (Optional) Verify setup:"
echo "     ./scripts/verify-setup.sh"
echo ""
