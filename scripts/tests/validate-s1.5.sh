#!/bin/bash
# S1.5 Validation Script - Early Agent Integration
# Run from project root: bash scripts/tests/validate-s1.5.sh

set -e
ROOT="${ROOT:-$(pwd)}"
DOX="python3 $ROOT/scripts/dox.py"

echo "=== S1.5: Early Agent Integration Validation ==="

# 1. Skill file exists
echo -n "1. Skill file exists at .claude/skills/doxagon/SKILL.md... "
if [ -f "$ROOT/.claude/skills/doxagon/SKILL.md" ]; then
    echo "PASS"
else
    echo "FAIL: Skill file not found"
    exit 1
fi

# 2. Skill file has required content
echo -n "2. SKILL.md contains essential commands documentation... "
SKILL_CONTENT=$(cat "$ROOT/.claude/skills/doxagon/SKILL.md")
if echo "$SKILL_CONTENT" | grep -q "capture" && \
   echo "$SKILL_CONTENT" | grep -q "show" && \
   echo "$SKILL_CONTENT" | grep -q "related"; then
    echo "PASS"
else
    echo "FAIL: Missing command documentation in SKILL.md"
    exit 1
fi

# 3. /capture command exists
echo -n "3. /capture command file exists... "
if [ -f "$ROOT/.claude/commands/capture.md" ]; then
    echo "PASS"
else
    echo "SKIP (slash commands not yet implemented)"
fi

# 4. Smoke test: Full workflow works
echo -n "4. Smoke test: capture -> show -> link workflow... "

cleanup_smoke() {
    rm -f "$ROOT/library/doxai/d-smoke-test-belief"*.md 2>/dev/null || true
    rm -f "$ROOT/library/doxai/d-smoke-target.md" 2>/dev/null || true
    if [ -f "$ROOT/library/logos.yaml.smoke-bak" ]; then
        mv "$ROOT/library/logos.yaml.smoke-bak" "$ROOT/library/logos.yaml"
    fi
}
trap cleanup_smoke EXIT

# Capture
$DOX capture "Smoke test belief for S1.5" >/dev/null 2>&1
CAPTURED=$(ls "$ROOT/library/doxai/d-smoke-test-belief"*.md 2>/dev/null | head -1)
if [ -z "$CAPTURED" ]; then
    echo "FAIL: capture step failed"
    exit 1
fi
CAPTURED_ID=$(basename "$CAPTURED" .md)

# Show
if ! $DOX show "$CAPTURED_ID" 2>&1 | grep -q "Smoke test belief"; then
    echo "FAIL: show step failed"
    exit 1
fi

# Create target for linking
cat > "$ROOT/library/doxai/d-smoke-target.md" << 'EOF'
---
belief: "Smoke test target"
status: draft
tags: []
evidence: []
---
# Smoke Target
EOF

# Backup logos
cp "$ROOT/library/logos.yaml" "$ROOT/library/logos.yaml.smoke-bak"

# Link
$DOX link "$CAPTURED_ID" d-smoke-target grounds >/dev/null 2>&1

# Verify
if $DOX related "$CAPTURED_ID" 2>&1 | grep -q "d-smoke-target"; then
    echo "PASS"
else
    echo "FAIL: link/related step failed"
    exit 1
fi

echo ""
echo "S1.5 COMPLETE: All validations passed"
