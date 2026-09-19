#!/bin/bash
# S1.1 Validation Script - Schema Definition
# Run from project root: bash scripts/tests/validate-s1.1.sh

set -e
ROOT="${ROOT:-$(pwd)}"

echo "=== S1.1: Schema Definition Validation ==="

# 1. schema.yaml exists and is valid YAML
echo -n "1. schema.yaml exists and parses... "
python3 -c "import yaml; yaml.safe_load(open('$ROOT/library/schema.yaml'))" && echo "PASS" || { echo "FAIL"; exit 1; }

# 2. schema.yaml has required node_types
echo -n "2. schema.yaml has node_types (doxa, evidence, diegesis)... "
python3 -c "
import yaml
s = yaml.safe_load(open('$ROOT/library/schema.yaml'))
nt = s.get('node_types', {})
required = {'doxa', 'evidence', 'diegesis'}
actual = set(nt.keys())
assert required.issubset(actual), f'Missing: {required - actual}'
for t in required:
    assert 'prefix' in nt[t], f'{t} missing prefix'
    assert 'location' in nt[t], f'{t} missing location'
print('PASS')
" || { echo "FAIL"; exit 1; }

# 3. schema.yaml has required edge_types
echo -n "3. schema.yaml has edge_types (grounds, contradicts)... "
python3 -c "
import yaml
s = yaml.safe_load(open('$ROOT/library/schema.yaml'))
et = s.get('edge_types', {})
required = {'grounds', 'contradicts'}
actual = set(et.keys())
assert required.issubset(actual), f'Missing: {required - actual}'
print('PASS')
" || { echo "FAIL"; exit 1; }

# 4. contradicts is marked symmetric
echo -n "4. 'contradicts' edge is symmetric... "
python3 -c "
import yaml
s = yaml.safe_load(open('$ROOT/library/schema.yaml'))
assert s['edge_types']['contradicts'].get('symmetric') == True
print('PASS')
" || { echo "FAIL"; exit 1; }

# 5. tag_prefixes has controlled domain values
echo -n "5. tag_prefixes.domain is controlled with values... "
python3 -c "
import yaml
s = yaml.safe_load(open('$ROOT/library/schema.yaml'))
domain = s.get('tag_prefixes', {}).get('domain', {})
assert domain.get('controlled') == True, 'domain not marked controlled'
assert len(domain.get('values', [])) > 0, 'domain has no values'
print('PASS')
" || { echo "FAIL"; exit 1; }

# 6. logos.yaml exists and has edges key
echo -n "6. logos.yaml exists with edges key... "
python3 -c "
import yaml
l = yaml.safe_load(open('$ROOT/library/logos.yaml'))
assert 'edges' in l, 'logos.yaml missing edges key'
assert isinstance(l['edges'], list) or l['edges'] is None, 'edges not a list'
print('PASS')
" || { echo "FAIL"; exit 1; }

# 7. Directory structure exists
echo -n "7. Library directories exist... "
[ -d "$ROOT/library/doxai" ] && [ -d "$ROOT/library/evidence" ] && [ -d "$ROOT/library/diegeses" ] && echo "PASS" || { echo "FAIL"; exit 1; }

echo ""
echo "S1.1 COMPLETE: All validations passed"
