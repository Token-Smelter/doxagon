#!/bin/bash
# S1.2 Validation Script - Core CLI (list, show, search, validate)
# Run from project root: bash scripts/tests/validate-s1.2.sh

set -e
ROOT="${ROOT:-$(pwd)}"
DOX="python3 $ROOT/scripts/dox.py"

echo "=== S1.2: Core CLI Validation ==="

# Setup: Create test fixtures
setup_fixtures() {
    cat > "$ROOT/library/doxai/d-test-belief-one.md" << 'EOF'
---
belief: "Test belief one for validation"
status: draft
tags:
  - domain:ai-economics
evidence:
  - source: e-test-evidence
    quote: "Test quote from evidence"
created: 2025-12-24
---
# Test Belief One

Test body content.
EOF

    cat > "$ROOT/library/doxai/d-test-belief-two.md" << 'EOF'
---
belief: "Test belief two for validation"
status: canonical
tags:
  - domain:software-engineering
evidence: []
created: 2025-12-24
---
# Test Belief Two

Another test doxa.
EOF

    cat > "$ROOT/library/evidence/e-test-evidence.md" << 'EOF'
---
type: report
title: "Test Evidence Report"
url: "https://example.com/report"
date: 2025-01-01
created: 2025-12-24
---
# Test Evidence Report

## Key Excerpts
Test quote from evidence.
EOF
}

cleanup_fixtures() {
    rm -f "$ROOT/library/doxai/d-test-belief-one.md" 2>/dev/null || true
    rm -f "$ROOT/library/doxai/d-test-belief-two.md" 2>/dev/null || true
    rm -f "$ROOT/library/evidence/e-test-evidence.md" 2>/dev/null || true
    rm -f "$ROOT/library/doxai/d-bad-domain-test.md" 2>/dev/null || true
    rm -f "$ROOT/library/doxai/d-bad-evidence-test.md" 2>/dev/null || true
}

trap cleanup_fixtures EXIT
setup_fixtures

# 1. dox list shows files from library/doxai/
echo -n "1. 'dox list' shows doxai... "
OUTPUT=$($DOX list 2>&1)
if echo "$OUTPUT" | grep -q "d-test-belief-one"; then
    echo "PASS"
else
    echo "FAIL: d-test-belief-one not in output"
    exit 1
fi

# 2. dox show displays belief and evidence
echo -n "2. 'dox show' displays belief text and evidence... "
OUTPUT=$($DOX show d-test-belief-one 2>&1)
if echo "$OUTPUT" | grep -q "Test belief one" && echo "$OUTPUT" | grep -q "e-test-evidence"; then
    echo "PASS"
else
    echo "FAIL: Missing belief or evidence in show output"
    exit 1
fi

# 3. dox search finds matching doxai
echo -n "3. 'dox search' finds matching doxai... "
OUTPUT=$($DOX search "validation" 2>&1)
if echo "$OUTPUT" | grep -q "d-test-belief"; then
    echo "PASS"
else
    echo "FAIL: search did not find test beliefs"
    exit 1
fi

# 4. dox validate catches missing doxa referenced in logos
echo -n "4. 'dox validate' catches missing doxa in logos... "
ORIG_LOGOS=$(cat "$ROOT/library/logos.yaml")
echo "edges: [[d-nonexistent, d-test-belief-one, grounds]]" > "$ROOT/library/logos.yaml"
if $DOX validate 2>&1 | grep -q "d-nonexistent"; then
    echo "PASS"
else
    echo "FAIL: did not catch missing doxa"
    echo "$ORIG_LOGOS" > "$ROOT/library/logos.yaml"
    exit 1
fi
echo "$ORIG_LOGOS" > "$ROOT/library/logos.yaml"

# 5. dox validate catches undefined domain tag
echo -n "5. 'dox validate' catches undefined domain tag... "
cat > "$ROOT/library/doxai/d-bad-domain-test.md" << 'EOF'
---
belief: "Bad domain test"
status: draft
tags:
  - domain:fake-domain-xyz
evidence: []
---
# Bad Domain Test
EOF
if $DOX validate 2>&1 | grep -qi "domain\|tag"; then
    echo "PASS"
else
    echo "FAIL: did not catch invalid domain tag"
    exit 1
fi
rm -f "$ROOT/library/doxai/d-bad-domain-test.md"

# 6. dox validate catches missing evidence file
echo -n "6. 'dox validate' catches missing evidence file... "
cat > "$ROOT/library/doxai/d-bad-evidence-test.md" << 'EOF'
---
belief: "Bad evidence test"
status: draft
tags: []
evidence:
  - source: e-nonexistent-evidence-xyz
    quote: "This should fail"
---
# Bad Evidence Test
EOF
if $DOX validate 2>&1 | grep -q "e-nonexistent-evidence-xyz"; then
    echo "PASS"
else
    echo "FAIL: did not catch missing evidence file"
    exit 1
fi
rm -f "$ROOT/library/doxai/d-bad-evidence-test.md"

echo ""
echo "S1.2 COMPLETE: All validations passed"
