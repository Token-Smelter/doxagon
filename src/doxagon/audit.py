"""Edge audit pipeline for evaluating and hydrating edge metadata.

This module handles:
1. Loading all doxai beliefs and edges
2. Calling Gemini for comprehensive edge evaluation
3. Parsing audit results
4. Applying corrections to logos.yaml
"""

import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import frontmatter
import yaml

from doxagon.config import DOXAI_DIR, LOGOS_FILE
from doxagon.graph import invalidate_cache
from doxagon.prompts import load_prompt
from doxagon.storage import write_logos


@dataclass
class EdgeAudit:
    """Result of auditing a single edge."""
    source: str
    target: str
    current_type: str
    verdict: str  # CONFIRM | CORRECT
    correct_type: str
    alias: str  # Human-readable label for this relationship
    confidence: str  # high | medium | low
    rationale: str
    flags: list[str] = field(default_factory=list)


@dataclass
class AuditResult:
    """Result of full audit pass."""
    audits: list[EdgeAudit] = field(default_factory=list)
    confirmed: int = 0
    corrected: int = 0
    errors: list[str] = field(default_factory=list)


def load_beliefs_summary() -> str:
    """Load all doxai beliefs as slug: belief pairs."""
    lines = []
    for f in sorted(DOXAI_DIR.glob("d-*.md")):
        try:
            post = frontmatter.load(f)
            belief = post.get("belief", "")
            if belief:
                lines.append(f'{f.stem}: "{belief}"')
        except Exception:
            continue
    return "\n".join(lines) if lines else "(No beliefs found)"


def load_edges_summary() -> tuple[str, int]:
    """Load all edges as source → target [type] format. Returns (summary, count)."""
    if not LOGOS_FILE.exists():
        return "(No edges defined)", 0

    try:
        data = yaml.safe_load(LOGOS_FILE.read_text())
        edges = data.get('edges', [])
        if not edges:
            return "(No edges defined)", 0

        lines = []
        for edge in edges:
            if isinstance(edge, list):
                source = edge[0] if len(edge) > 0 else "?"
                target = edge[1] if len(edge) > 1 else "?"
                edge_type = edge[2] if len(edge) > 2 else "unknown"
            else:
                source = edge.get('source', '?')
                target = edge.get('target', '?')
                edge_type = edge.get('type', 'unknown')
            lines.append(f"{source} → {target} [{edge_type}]")

        return "\n".join(lines), len(edges)
    except Exception as e:
        return f"(Error loading edges: {e})", 0


def call_gemini(prompt: str, model: str = "gemini-2.5-pro") -> str:
    """Call gemini CLI with a prompt and return the response.

    Uses gemini-2.5-pro for large context window (1M tokens).
    """
    result = subprocess.run(
        ["gemini", "-m", model],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=600,  # 10 minutes for full audit
    )
    if result.returncode != 0:
        raise RuntimeError(f"Gemini CLI error: {result.stderr}")
    return result.stdout.strip()


def parse_audit_response(response: str) -> AuditResult:
    """Parse audit response into structured results."""
    result = AuditResult()

    # Parse AUDIT blocks
    audit_pattern = r'===AUDIT===(.*?)===END_AUDIT==='
    for match in re.finditer(audit_pattern, response, re.DOTALL):
        content = match.group(1).strip()
        audit = _parse_yaml_block(content)

        if audit and 'source' in audit and 'target' in audit:
            verdict = audit.get('verdict', 'CONFIRM').upper()
            edge_audit = EdgeAudit(
                source=audit.get('source', ''),
                target=audit.get('target', ''),
                current_type=audit.get('current_type', ''),
                verdict=verdict,
                correct_type=audit.get('correct_type', audit.get('current_type', '')),
                alias=audit.get('alias', ''),
                confidence=audit.get('confidence', 'medium'),
                rationale=audit.get('rationale', ''),
                flags=audit.get('flags', []) or [],
            )
            result.audits.append(edge_audit)

            if verdict == 'CONFIRM':
                result.confirmed += 1
            else:
                result.corrected += 1

    return result


def _parse_yaml_block(content: str) -> dict:
    """Parse a YAML-like block into a dictionary."""
    try:
        return yaml.safe_load(content) or {}
    except Exception:
        # Fall back to simple key: value parsing
        result = {}
        current_key = None
        current_value = []

        for line in content.split('\n'):
            if ':' in line and not line.startswith(' ') and not line.startswith('-'):
                # Save previous key
                if current_key:
                    val = '\n'.join(current_value).strip()
                    result[current_key] = val if val else result.get(current_key, '')
                # Start new key
                key, value = line.split(':', 1)
                current_key = key.strip()
                current_value = [value.strip()] if value.strip() else []
            elif current_key:
                current_value.append(line)

        # Save last key
        if current_key:
            val = '\n'.join(current_value).strip()
            result[current_key] = val if val else result.get(current_key, '')

        return result


def apply_audit_results(audits: list[EdgeAudit], apply_corrections: bool = True) -> dict:
    """Apply audit results to logos.yaml.

    Updates edges with:
    - rationale (always)
    - confidence (always)
    - type (only if CORRECT and apply_corrections=True)

    Returns summary of changes.
    """
    if not audits:
        return {'updated': 0, 'type_changes': 0}

    # Load existing
    logos = yaml.safe_load(LOGOS_FILE.read_text()) if LOGOS_FILE.exists() else {}
    edges = logos.get('edges', [])

    # Build index for fast lookup
    edge_index = {}
    for i, edge in enumerate(edges):
        if isinstance(edge, list):
            key = (edge[0], edge[1], edge[2] if len(edge) > 2 else 'supports')
        else:
            key = (edge.get('source', ''), edge.get('target', ''), edge.get('type', ''))
        edge_index[key] = i

    updated = 0
    type_changes = 0

    for audit in audits:
        key = (audit.source, audit.target, audit.current_type)
        if key not in edge_index:
            continue

        idx = edge_index[key]
        edge = edges[idx]

        # Normalize legacy format
        if isinstance(edge, list):
            edge = {
                'source': edge[0],
                'target': edge[1],
                'type': edge[2] if len(edge) > 2 else 'supports',
                'strength': 'moderate',
            }

        # Update rationale, confidence, and alias
        edge['rationale'] = audit.rationale
        edge['confidence'] = audit.confidence
        if audit.alias:
            edge['alias'] = audit.alias

        # Update type if corrected and applying corrections
        if audit.verdict == 'CORRECT' and apply_corrections:
            if edge.get('type') != audit.correct_type:
                old_type = edge.get('type', 'unknown')
                edge['type'] = audit.correct_type
                edge['reviewer_notes'] = f"Corrected from '{old_type}' to '{audit.correct_type}' by audit pass on {date.today().isoformat()}"
                type_changes += 1

        # Add audit provenance
        if 'provenance' not in edge:
            edge['provenance'] = {}
        edge['provenance']['audit'] = date.today().isoformat()

        edges[idx] = edge
        updated += 1

    # Save only after the complete typed-edge set validates.
    logos['edges'] = edges
    write_logos(logos)
    invalidate_cache()

    return {'updated': updated, 'type_changes': type_changes}


def run_audit(
    apply: bool = False,
    model: str = "gemini-2.5-pro",
) -> AuditResult:
    """Run full edge audit pass.

    Args:
        apply: If True, apply corrections to logos.yaml
        model: Gemini model to use (default: gemini-2.5-pro for large context)

    Returns:
        AuditResult with all audits and summary
    """
    # Load content
    beliefs_summary = load_beliefs_summary()
    edges_summary, edge_count = load_edges_summary()

    if edge_count == 0:
        result = AuditResult()
        result.errors.append("No edges to audit")
        return result

    # Build prompt
    prompt = load_prompt(
        "audit",
        doxai_content=beliefs_summary,
        edges_content=edges_summary,
        edge_count=edge_count,
    )

    # Call Gemini
    print(f"Auditing {edge_count} edges with {model}...")
    response = call_gemini(prompt, model=model)

    # Parse response
    result = parse_audit_response(response)

    # Apply if requested
    if apply and result.audits:
        changes = apply_audit_results(result.audits, apply_corrections=True)
        print(f"Applied: {changes['updated']} edges updated, {changes['type_changes']} type corrections")

    return result
