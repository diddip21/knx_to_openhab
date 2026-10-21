#!/usr/bin/env bash
# Development Server Start Script for Linux/macOS
# Starts Flask development server with debug mode

set -euo pipefail

echo "🚀 Starting KNX to OpenHAB Web UI (Development Server)"
echo ""

# Check if venv exists
if [ ! -d ".venv" ]; then
    echo "❌ Virtual environment not found!"
    echo "   Please run: ./scripts/dev-setup.sh"
    exit 1
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source .venv/bin/activate

# Start Flask development server
echo ""
echo "🌐 Starting Flask development server..."
echo "   URL: http://localhost:5000"
echo "   Press Ctrl+C to stop"
echo ""

# Set Flask environment variables and start
export FLASK_APP="web_ui.backend.app:app"
export FLASK_ENV="testing"

flask run --host 127.0.0.1 --port 5000 --debug
