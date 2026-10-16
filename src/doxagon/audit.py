"""Audit: confirm or correct each edge's type and rationale, judged by the calling agent.

`audit_context` returns a page of edges with both endpoint beliefs.
`apply_audit` validates every verdict against the current graph before writing.
"""

from __future__ import annotations

from datetime import date

from doxagon import agent_context
from doxagon.graph import invalidate_cache
from doxagon.storage import check_logos, write_logos
from doxagon.validation import GraphIntegrityError, ValidationIssue, ValidationReport

AUDIT_FIELDS = ("source", "target", "current_type", "verdict", "rationale")


def audit_context(offset: int = 0, limit: int | None = None) -> dict:
    """Return a page of edges, each with its endpoint beliefs and current annotations."""
    edges = agent_context.read_logos()['edges']
    page = edges[offset:offset + limit if limit else None]
    beliefs = {b['slug']: b['belief'] for b in agent_context.beliefs()}
    return {
        'schema': 'doxagon.audit-context/1',
        'total_edges': len(edges),
        'offset': offset,
        'edges': [{
            'source': e.get('source'), 'source_belief': beliefs.get(e.get('source'), ''),
            'target': e.get('target'), 'target_belief': beliefs.get(e.get('target'), ''),
            'type': e.get('type'),
            **{k: e[k] for k in ('alias', 'rationale', 'confidence') if e.get(k)},
        } for e in page],
        **agent_context.vocabulary(),
        'answer_format': 'dox-knowledge skill, references/audit.md',
    }


def apply_audit(response: str, dry_run: bool = False) -> dict:
    """Validate ===AUDIT=== verdicts against the current graph, then write them."""
    blocks = agent_context.parse_blocks(response, 'AUDIT')
    if not blocks:
        raise ValueError("Response has no ===AUDIT=== blocks")
    report = ValidationReport()
    logos = agent_context.read_logos()
    index = {agent_context.edge_key(e): i for i, e in enumerate(logos['edges'])}
    confirmed, corrected = [], []
    today = date.today().isoformat()
    for number, block in enumerate(blocks, start=1):
        missing = [name for name in AUDIT_FIELDS if not str(block.get(name) or '').strip()]
        verdict = str(block.get('verdict', '')).upper()
        key = (block.get('source'), block.get('target'), block.get('current_type'))
        problem = ("not a YAML mapping" if '_invalid' in block
                   else f"missing {', '.join(missing)}" if missing
                   else f"verdict must be CONFIRM or CORRECT, not {verdict!r}" if verdict not in ('CONFIRM', 'CORRECT')
                   else "CORRECT needs correct_type" if verdict == 'CORRECT' and not block.get('correct_type')
                   else f"no edge {key[0]} -[{key[2]}]-> {key[1]}" if key not in index
                   else None)
        if problem:
            report.issues.append(ValidationIssue("invalid_block", f"AUDIT {number}: {problem}"))
            continue
        edge = logos['edges'][index[key]]
        edge['rationale'] = str(block['rationale']).strip()
        for name in ('alias', 'confidence'):
            if block.get(name):
                edge[name] = block[name]
        if verdict == 'CORRECT' and block['correct_type'] != edge['type']:
            edge['reviewer_notes'] = f"Corrected from '{edge['type']}' to '{block['correct_type']}' by audit on {today}"
            edge['type'] = block['correct_type']
            corrected.append((key, block['correct_type']))
        else:
            confirmed.append(key)
        provenance = edge.get('provenance')
        provenance = provenance if isinstance(provenance, dict) else ({'method': provenance} if provenance else {})
        edge['provenance'] = {**provenance, 'audit': today}
    report.extend(check_logos(logos))
    if not report.valid:
        raise GraphIntegrityError(report)
    if not dry_run:
        write_logos(logos)
        invalidate_cache()
    return {'confirmed': confirmed, 'corrected': corrected}
