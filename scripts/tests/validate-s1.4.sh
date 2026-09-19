#!/bin/bash
# S1.4 Validation Script - Graph Operations (link, unlink, related)
# Run from project root: bash scripts/tests/validate-s1.4.sh

set -e
ROOT="${ROOT:-$(pwd)}"
DOX="python3 $ROOT/scripts/dox.py"

echo "=== S1.4: Graph Operations Validation ==="

setup_graph_fixtures() {
    cat > "$ROOT/library/doxai/d-graph-test-a.md" << 'EOF'
---
belief: "Graph test doxa A"
status: draft
tags: []
evidence: []
---
# Graph Test A
EOF
    cat > "$ROOT/library/doxai/d-graph-test-b.md" << 'EOF'
---
belief: "Graph test doxa B"
status: draft
tags: []
evidence: []
---
# Graph Test B
EOF
    cp "$ROOT/library/logos.yaml" "$ROOT/library/logos.yaml.bak"
}

cleanup_graph_fixtures() {
    rm -f "$ROOT/library/doxai/d-graph-test-"*.md 2>/dev/null || true
    if [ -f "$ROOT/library/logos.yaml.bak" ]; then
        mv "$ROOT/library/logos.yaml.bak" "$ROOT/library/logos.yaml"
    fi
}

trap cleanup_graph_fixtures EXIT
setup_graph_fixtures

# 1. dox link adds edge to logos.yaml
echo -n "1. 'dox link' adds edge to logos.yaml... "
$DOX link d-graph-test-a d-graph-test-b grounds >/dev/null 2>&1
if grep -q "d-graph-test-a" "$ROOT/library/logos.yaml" && grep -q "d-graph-test-b" "$ROOT/library/logos.yaml"; then
    echo "PASS"
else
    echo "FAIL: Edge not found in logos.yaml"
    exit 1
fi

# 2. dox related shows the edge
echo -n "2. 'dox related' shows outgoing edges... "
OUTPUT=$($DOX related d-graph-test-a 2>&1)
if echo "$OUTPUT" | grep -q "d-graph-test-b" && echo "$OUTPUT" | grep -q "grounds"; then
    echo "PASS"
else
    echo "FAIL: Edge not shown in related output"
    exit 1
fi

# 3. dox related shows inverse (incoming)
echo -n "3. 'dox related' shows incoming edges... "
OUTPUT=$($DOX related d-graph-test-b 2>&1)
if echo "$OUTPUT" | grep -q "d-graph-test-a"; then
    echo "PASS"
else
    echo "FAIL: Incoming edge not shown"
    exit 1
fi

# 4. dox unlink removes edge from logos.yaml
echo -n "4. 'dox unlink' removes edge from logos.yaml... "
$DOX unlink d-graph-test-a d-graph-test-b grounds >/dev/null 2>&1
if python3 -c "
import yaml
l = yaml.safe_load(open('$ROOT/library/logos.yaml'))
edges = l.get('edges', []) or []
found = any(e[0] == 'd-graph-test-a' and e[1] == 'd-graph-test-b' for e in edges)
exit(0 if not found else 1)
"; then
    echo "PASS"
else
    echo "FAIL: Edge still exists after unlink"
    exit 1
fi

# 5. Link validation - rejects invalid edge type
echo -n "5. 'dox link' rejects invalid edge type... "
if ! $DOX link d-graph-test-a d-graph-test-b invalidtype 2>&1 | grep -qi "invalid\|error\|unknown"; then
    if grep -q "invalidtype" "$ROOT/library/logos.yaml"; then
        echo "FAIL: Invalid edge type was accepted"
        exit 1
    fi
fi
echo "PASS"

# 6. Link validation - rejects self-loops
echo -n "6. 'dox link' rejects self-loops... "
$DOX link d-graph-test-a d-graph-test-a grounds 2>&1 || true
if python3 -c "
import yaml
l = yaml.safe_load(open('$ROOT/library/logos.yaml'))
edges = l.get('edges', []) or []
found = any(e[0] == 'd-graph-test-a' and e[1] == 'd-graph-test-a' for e in edges)
exit(0 if not found else 1)
"; then
    echo "PASS"
else
    echo "FAIL: Self-loop was created"
    exit 1
fi

# 7. Link validation - rejects duplicate edges
echo -n "7. 'dox link' rejects duplicate edges... "
$DOX link d-graph-test-a d-graph-test-b grounds >/dev/null 2>&1
$DOX link d-graph-test-a d-graph-test-b grounds >/dev/null 2>&1 || true
COUNT=$(python3 -c "
import yaml
l = yaml.safe_load(open('$ROOT/library/logos.yaml'))
edges = l.get('edges', []) or []
count = sum(1 for e in edges if e[0] == 'd-graph-test-a' and e[1] == 'd-graph-test-b')
print(count)
")
if [ "$COUNT" -eq 1 ]; then
    echo "PASS"
else
    echo "FAIL: Duplicate edge created (count: $COUNT)"
    exit 1
fi

echo ""
echo "S1.4 COMPLETE: All validations passed"
