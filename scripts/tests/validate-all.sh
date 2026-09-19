#!/bin/bash
# Master validation script - runs all story validations
# Run from project root: bash scripts/tests/validate-all.sh

ROOT="${ROOT:-$(pwd)}"
TESTS_DIR="$ROOT/scripts/tests"

# Activate virtual environment if available
if [ -f "$ROOT/.venv/bin/activate" ]; then
    source "$ROOT/.venv/bin/activate"
fi

echo "========================================"
echo "DOXAGON IMPLEMENTATION VALIDATION SUITE"
echo "========================================"
echo ""

FAILED=0
PASSED=0
SKIPPED=0

run_validation() {
    local script="$1"
    local name="$2"

    echo "----------------------------------------"
    echo "Running: $name"
    echo "----------------------------------------"
    if [ -f "$script" ]; then
        if bash "$script"; then
            ((PASSED++))
            echo ""
        else
            ((FAILED++))
            echo "^^^ FAILED: $name"
            echo ""
        fi
    else
        echo "  SKIP: Script not found"
        ((SKIPPED++))
        echo ""
    fi
}

run_validation "$TESTS_DIR/validate-s1.1.sh" "S1.1: Schema Definition"
run_validation "$TESTS_DIR/validate-s1.2.sh" "S1.2: Core CLI"
run_validation "$TESTS_DIR/validate-s1.3.sh" "S1.3: CLI Enhancements"
run_validation "$TESTS_DIR/validate-s1.4.sh" "S1.4: Graph Operations"
run_validation "$TESTS_DIR/validate-s1.5.sh" "S1.5: Agent Integration"

echo "========================================"
echo "SUMMARY"
echo "========================================"
echo "  Passed:  $PASSED"
echo "  Failed:  $FAILED"
echo "  Skipped: $SKIPPED"
echo ""

if [ $FAILED -gt 0 ]; then
    echo "RESULT: FAIL"
    exit 1
else
    echo "RESULT: PASS"
    exit 0
fi
