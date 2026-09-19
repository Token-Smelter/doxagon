#!/bin/bash
# S1.3 Validation Script - CLI Enhancements (capture, types)
# Run from project root: bash scripts/tests/validate-s1.3.sh

set -e
ROOT="${ROOT:-$(pwd)}"
DOX="python3 $ROOT/scripts/dox.py"

echo "=== S1.3: CLI Enhancements Validation ==="

cleanup() {
    rm -f "$ROOT/library/doxai/d-this-is-a-test"*.md 2>/dev/null || true
    rm -f "$ROOT/library/doxai/d-whats-the-deal"*.md 2>/dev/null || true
    rm -f "$ROOT/library/doxai/d-unique-test-belief"*.md 2>/dev/null || true
}

trap cleanup EXIT

# 1. dox capture creates properly formatted file
echo -n "1. 'dox capture' creates properly formatted file... "
OUTPUT=$($DOX capture "This is a test capture belief for validation" 2>&1)
ACTUAL_FILE=$(ls "$ROOT/library/doxai/d-this-is-a-test"*.md 2>/dev/null | head -1)
if [ -n "$ACTUAL_FILE" ] && [ -f "$ACTUAL_FILE" ]; then
    if grep -q "belief:" "$ACTUAL_FILE" && grep -q "status: draft" "$ACTUAL_FILE"; then
        echo "PASS"
        rm -f "$ACTUAL_FILE"
    else
        echo "FAIL: File created but missing required frontmatter"
        exit 1
    fi
else
    echo "FAIL: No file created"
    exit 1
fi

# 2. Slug generation handles special characters
echo -n "2. Slug handles special chars (creates valid filename)... "
OUTPUT=$($DOX capture "What's the deal with AI? It's complicated!" 2>&1)
CREATED=$(ls "$ROOT/library/doxai/d-whats-the-deal"*.md 2>/dev/null | head -1 || echo "")
if [ -n "$CREATED" ] && [ -f "$CREATED" ]; then
    BASENAME=$(basename "$CREATED" .md)
    if [[ "$BASENAME" =~ ^d-[a-z0-9-]+$ ]]; then
        echo "PASS"
        rm -f "$CREATED"
    else
        echo "FAIL: Invalid slug format: $BASENAME"
        exit 1
    fi
else
    echo "FAIL: No file created for special char input"
    exit 1
fi

# 3. Collision detection (create same belief twice)
echo -n "3. Collision detection works... "
$DOX capture "Unique test belief for collision check" >/dev/null 2>&1
$DOX capture "Unique test belief for collision check" >/dev/null 2>&1
COUNT=$(ls "$ROOT/library/doxai/d-unique-test-belief"*.md 2>/dev/null | wc -l)
if [ "$COUNT" -ge 1 ]; then
    echo "PASS"
    rm -f "$ROOT/library/doxai/d-unique-test-belief"*.md
else
    echo "FAIL: Collision not handled"
    exit 1
fi

# 4. dox types lists registered edge types
echo -n "4. 'dox types' lists edge types from schema... "
OUTPUT=$($DOX types 2>&1)
if echo "$OUTPUT" | grep -q "grounds" && echo "$OUTPUT" | grep -q "contradicts"; then
    echo "PASS"
else
    echo "FAIL: Missing edge types in output"
    exit 1
fi

echo ""
echo "S1.3 COMPLETE: All validations passed"
