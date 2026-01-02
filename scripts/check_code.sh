#!/bin/bash
# Local code quality check script
# Run this before committing code

set -e

echo "======================================"
echo "  KNX to OpenHAB - Code Quality Check"
echo "======================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if required tools are installed
command -v python >/dev/null 2>&1 || { echo -e "${RED}❌ Python is required but not installed.${NC}" >&2; exit 1; }

# Install tools if not present
echo "Checking for required tools..."
pip install -q flake8 black isort pylint bandit 2>/dev/null || true

ERROR_COUNT=0

# 1. Python Syntax Check
echo -e "${YELLOW}[1/7]${NC} Checking Python syntax..."
if python -m py_compile *.py 2>/dev/null && \
   find . -name '*.py' -not -path './venv/*' -not -path './.venv/*' -not -path './.git/*' -not -path './build/*' -not -path './dist/*' -exec python -m py_compile {} \; 2>/dev/null; then
    echo -e "${GREEN}✓ Syntax check passed${NC}"
else
    echo -e "${RED}❌ Syntax errors found${NC}"
    ERROR_COUNT=$((ERROR_COUNT + 1))
fi

# 2. Flake8 Critical Errors
echo -e "${YELLOW}[2/7]${NC} Checking for critical code issues (flake8)..."
if flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics \
    --exclude=venv,.venv,.git,__pycache__,build,dist,*.egg-info 2>/dev/null; then
    echo -e "${GREEN}✓ No critical errors${NC}"
else
    echo -e "${RED}❌ Critical errors found${NC}"
    ERROR_COUNT=$((ERROR_COUNT + 1))
fi

# 3. Code Formatting (Black) - Warning only
echo -e "${YELLOW}[3/7]${NC} Checking code formatting (black)..."
if black --check --quiet . --exclude='/(venv|.venv|.git|__pycache__|build|dist|.eggs)/' 2>/dev/null; then
    echo -e "${GREEN}✓ Code is properly formatted${NC}"
else
    echo -e "${YELLOW}⚠️  Code formatting issues detected. Run 'black .' to fix.${NC}"
fi

# 4. Import Sorting (isort) - Warning only
echo -e "${YELLOW}[4/7]${NC} Checking import order (isort)..."
if isort --check-only --quiet . --skip venv --skip .venv --skip .git 2>/dev/null; then
    echo -e "${GREEN}✓ Imports are properly sorted${NC}"
else
    echo -e "${YELLOW}⚠️  Import order issues detected. Run 'isort .' to fix.${NC}"
fi

# 5. JSON Validation
echo -e "${YELLOW}[5/7]${NC} Validating JSON files..."
JSON_ERROR=0
for json_file in $(find . -name '*.json' -not -path './venv/*' -not -path './.venv/*' -not -path './node_modules/*' 2>/dev/null); do
    if ! python -c "import json; json.load(open('$json_file'))" 2>/dev/null; then
        echo -e "${RED}❌ Invalid JSON: $json_file${NC}"
        JSON_ERROR=1
    fi
done
if [ $JSON_ERROR -eq 0 ]; then
    echo -e "${GREEN}✓ All JSON files are valid${NC}"
else
    ERROR_COUNT=$((ERROR_COUNT + 1))
fi

# 6. Security Check (Bandit) - Warning only
echo -e "${YELLOW}[6/7]${NC} Checking for security issues (bandit)..."
if bandit -r . -ll -q -x venv,.venv,tests 2>/dev/null; then
    echo -e "${GREEN}✓ No high-severity security issues found${NC}"
else
    echo -e "${YELLOW}⚠️  Potential security issues detected${NC}"
fi

# 7. Trailing Whitespace Check - Warning only
echo -e "${YELLOW}[7/7]${NC} Checking for trailing whitespace..."
if ! find . -name '*.py' -not -path './venv/*' -not -path './.venv/*' -exec grep -l '[[:space:]]$' {} + 2>/dev/null; then
    echo -e "${GREEN}✓ No trailing whitespace found${NC}"
else
    echo -e "${YELLOW}⚠️  Trailing whitespace found in some files${NC}"
fi

echo ""
echo "======================================"
if [ $ERROR_COUNT -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo "======================================"
    exit 0
else
    echo -e "${RED}❌ $ERROR_COUNT error(s) found${NC}"
    echo "======================================"
    echo ""
    echo "Please fix the errors above before committing."
    exit 1
fi
