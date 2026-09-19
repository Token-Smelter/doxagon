"""Extraction pipeline for phantasia → doxai + evidence + edges.

This module handles:
1. Loading phantasia content
2. Building context (existing beliefs for dedup)
3. Calling Gemini for extraction
4. Parsing LLM output into artifacts
5. Validating artifacts (schema + dedup)
6. Writing validated artifacts to disk
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date

import frontmatter
import yaml

from doxagon.config import DOXAI_DIR, EVIDENCE_DIR, PHANTASIAI_DIR, LOGOS_FILE, LIBRARY_DIR
from doxagon.graph import invalidate_cache
from doxagon.prompts import load_prompt
from doxagon.storage import write_logos


def resolve_phantasia_content(phantasia) -> str:
    """Resolve the full content of a phantasia, following source file references.

    If the phantasia's source field points to a file (e.g., library/inbox/file.md),
    read that file and return its content. Otherwise return the phantasia body.
    """
    source = phantasia.get("source", "")
    content = phantasia.content or ""

    # Check if source is a library file path
    if source.startswith("library/"):
        source_path = LIBRARY_DIR.parent / source
        if source_path.exists():
            try:
                return source_path.read_text()
            except Exception:
                pass  # Fall through to body content

    # If body just says "See: path", try to read that path
    if content.strip().startswith("See:") or content.strip().startswith("## Source Content"):
        # Extract path from body
        lines = content.strip().split("\n")
        for line in lines:
            if line.strip().startswith("See:"):
                ref_path = line.split("See:", 1)[1].strip()
                if ref_path.startswith("library/"):
                    full_path = LIBRARY_DIR.parent / ref_path
                    if full_path.exists():
                        try:
                            return full_path.read_text()
                        except Exception:
                            pass

    return content


@dataclass
class ExtractedEdge:
    """Edge extracted from LLM response."""
    source: str
    target: str
    edge_type: str
    confidence: str = "medium"  # high | medium | low
    rationale: str = ""


@dataclass
class ExtractionResult:
    """Result of parsing LLM extraction output."""
    doxai: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    edges: list[ExtractedEdge] = field(default_factory=list)
    duplicates: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of validating extracted artifacts."""
    valid_doxai: list[tuple[str, str]] = field(default_factory=list)  # (slug, content)
    valid_evidence: list[tuple[str, str]] = field(default_factory=list)
    valid_edges: list[ExtractedEdge] = field(default_factory=list)
    skipped_duplicates: list[dict] = field(default_factory=list)
    suggested_links: list[tuple[str, str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def get_existing_beliefs() -> str:
    """Load all existing doxai beliefs for extraction context."""
    beliefs = []
    for f in sorted(DOXAI_DIR.glob("d-*.md")):
        try:
            post = frontmatter.load(f)
            belief = post.get("belief", "")
            if belief:
                beliefs.append(f"- {f.stem}: \"{belief}\"")
        except Exception:
            continue
    return "\n".join(beliefs) if beliefs else "(No existing beliefs)"


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def chunk_content(content: str, max_tokens: int = 12000) -> list[tuple[int, str]]:
    """Split content into chunks that fit within token limits.

    Returns list of (chunk_number, chunk_content) tuples.
    Splits on paragraph boundaries to preserve context.
    """
    # If content fits in one chunk, return as-is
    if estimate_tokens(content) <= max_tokens:
        return [(1, content)]

    chunks = []
    paragraphs = content.split("\n\n")
    current_chunk = []
    current_tokens = 0
    chunk_num = 1

    for para in paragraphs:
        para_tokens = estimate_tokens(para)

        # If single paragraph exceeds limit, split it further
        if para_tokens > max_tokens:
            # Flush current chunk first
            if current_chunk:
                chunks.append((chunk_num, "\n\n".join(current_chunk)))
                chunk_num += 1
                current_chunk = []
                current_tokens = 0

            # Split large paragraph by sentences
            sentences = para.replace(". ", ".\n").split("\n")
            for sent in sentences:
                sent_tokens = estimate_tokens(sent)
                if current_tokens + sent_tokens > max_tokens and current_chunk:
                    chunks.append((chunk_num, "\n\n".join(current_chunk)))
                    chunk_num += 1
                    current_chunk = [sent]
                    current_tokens = sent_tokens
                else:
                    current_chunk.append(sent)
                    current_tokens += sent_tokens
        elif current_tokens + para_tokens > max_tokens:
            # Flush current chunk and start new one
            if current_chunk:
                chunks.append((chunk_num, "\n\n".join(current_chunk)))
                chunk_num += 1
            current_chunk = [para]
            current_tokens = para_tokens
        else:
            current_chunk.append(para)
            current_tokens += para_tokens

    # Don't forget the last chunk
    if current_chunk:
        chunks.append((chunk_num, "\n\n".join(current_chunk)))

    return chunks


def generate_slug(text: str, max_length: int = 50) -> str:
    """Generate a valid filename slug from text."""
    slug = text.lower()
    slug = re.sub(r"['\"]", "", slug)
    slug = re.sub(r"[:\-–—]", " ", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-+", "-", slug)
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0]
    return slug


def call_gemini(prompt: str, model: str = "gemini-2.5-pro") -> str:
    """Call gemini CLI with a prompt and return the response.

    Uses stdin to pass the prompt to avoid command line length limits.
    The -p "" flag enables non-interactive mode while reading from stdin.
    """
    result = subprocess.run(
        ["gemini", "-m", model, "-p", ""],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=300,  # 5 min for large documents
    )
    if result.returncode != 0:
        raise RuntimeError(f"Gemini CLI error: {result.stderr}")
    return result.stdout.strip()


def parse_extraction_response(response: str) -> ExtractionResult:
    """Parse multi-artifact LLM response into structured result."""
    result = ExtractionResult()

    # Extract DOXA blocks
    doxa_pattern = r'===DOXA===(.*?)===END_DOXA==='
    for match in re.finditer(doxa_pattern, response, re.DOTALL):
        content = match.group(1).strip()
        if content:
            result.doxai.append(content)

    # Extract EVIDENCE blocks
    evidence_pattern = r'===EVIDENCE===(.*?)===END_EVIDENCE==='
    for match in re.finditer(evidence_pattern, response, re.DOTALL):
        content = match.group(1).strip()
        if content:
            result.evidence.append(content)

    # Extract EDGES block
    # Format: source|target|edge_type|confidence|rationale
    # Legacy format: source|target|edge_type|annotation (4 fields)
    edges_pattern = r'===EDGES===(.*?)===END_EDGES==='
    edges_match = re.search(edges_pattern, response, re.DOTALL)
    if edges_match:
        edges_content = edges_match.group(1).strip()
        for line in edges_content.split('\n'):
            line = line.strip()
            if '|' in line and not line.startswith('#') and not line.startswith('source'):
                parts = line.split('|')
                if len(parts) >= 3:
                    source = parts[0].strip()
                    target = parts[1].strip()
                    edge_type = parts[2].strip()

                    # Handle both new format (5 fields) and legacy format (4 fields)
                    if len(parts) >= 5:
                        # New format: source|target|type|confidence|rationale
                        confidence = parts[3].strip() if parts[3].strip() in ("high", "medium", "low") else "medium"
                        rationale = parts[4].strip()
                    elif len(parts) == 4:
                        # Legacy format: source|target|type|annotation (treat as rationale)
                        confidence = "medium"
                        rationale = parts[3].strip()
                    else:
                        confidence = "medium"
                        rationale = ""

                    result.edges.append(ExtractedEdge(
                        source=source,
                        target=target,
                        edge_type=edge_type,
                        confidence=confidence,
                        rationale=rationale,
                    ))

    # Extract DUPLICATE blocks
    duplicate_pattern = r'===DUPLICATE===(.*?)===END_DUPLICATE==='
    for match in re.finditer(duplicate_pattern, response, re.DOTALL):
        content = match.group(1).strip()
        dup = {}
        for line in content.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                dup[key.strip().lower()] = value.strip()
        if dup:
            result.duplicates.append(dup)

    return result


def validate_doxa(content: str) -> tuple[bool, str, dict]:
    """Validate a single doxa artifact. Returns (valid, error_msg, metadata)."""
    try:
        post = frontmatter.loads(content)
    except Exception as e:
        return False, f"Invalid frontmatter: {e}", {}

    # Required fields
    required = ['belief', 'status', 'provenance']
    missing = [f for f in required if f not in post.metadata]
    if missing:
        return False, f"Missing required fields: {missing}", {}

    # Belief must be non-empty
    belief = post.metadata.get('belief', '')
    if len(belief) < 10:
        return False, f"Belief too short: {belief}", {}

    return True, "", post.metadata


def validate_evidence(content: str) -> tuple[bool, str, dict]:
    """Validate a single evidence artifact. Returns (valid, error_msg, metadata)."""
    try:
        post = frontmatter.loads(content)
    except Exception as e:
        return False, f"Invalid frontmatter: {e}", {}

    # Required fields
    required = ['assertion', 'source', 'type', 'strength', 'status']
    missing = [f for f in required if f not in post.metadata]
    if missing:
        return False, f"Missing required fields: {missing}", {}

    return True, "", post.metadata


def check_dedup(belief: str) -> dict:
    """Run semantic dedup check on a belief. Returns parsed result."""
    try:
        result = subprocess.run(
            ["dox", "dedup", belief, "--json"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return {"result": "ERROR"}


def validate_extraction(parsed: ExtractionResult) -> ValidationResult:
    """Validate all parsed artifacts, including dedup checks."""
    result = ValidationResult()
    created_slugs: set[str] = set()

    # Validate and dedup doxai
    for content in parsed.doxai:
        valid, error, metadata = validate_doxa(content)
        if not valid:
            result.errors.append(f"Invalid doxa: {error}")
            continue

        belief = metadata.get('belief', '')

        # Check semantic dedup
        dedup = check_dedup(belief)
        if dedup.get('result') == 'DUPLICATE':
            result.skipped_duplicates.append({
                'belief': belief,
                'matches': dedup.get('slug', ''),
                'reason': dedup.get('reason', 'Semantic duplicate'),
            })
            continue
        elif dedup.get('result') == 'RELATED':
            # Still create, but suggest link
            result.suggested_links.append((
                f"d-{generate_slug(belief)}",
                dedup.get('slug', ''),
                'elaborates',
            ))

        # Generate slug with collision handling
        base_slug = generate_slug(belief)
        slug = f"d-{base_slug}"
        counter = 2
        while slug in created_slugs or (DOXAI_DIR / f"{slug}.md").exists():
            slug = f"d-{base_slug}-{counter}"
            counter += 1
        created_slugs.add(slug)

        result.valid_doxai.append((slug, content))

    # Build NEW:n to slug mapping for edges
    new_slug_mapping = {}
    for i, (slug, _) in enumerate(result.valid_doxai, start=1):
        new_slug_mapping[f"NEW:{i}"] = slug

    # Validate evidence
    for content in parsed.evidence:
        valid, error, metadata = validate_evidence(content)
        if not valid:
            result.errors.append(f"Invalid evidence: {error}")
            continue

        # Generate slug from assertion
        assertion = metadata.get('assertion', metadata.get('source', 'unknown'))
        base_slug = generate_slug(assertion)
        slug = f"e-{base_slug}"
        counter = 2
        while slug in created_slugs or (EVIDENCE_DIR / f"{slug}.md").exists():
            slug = f"e-{base_slug}-{counter}"
            counter += 1
        created_slugs.add(slug)

        result.valid_evidence.append((slug, content))

    # Map edge references (NEW:n -> actual slugs)
    for edge in parsed.edges:
        # Map NEW:n references to actual slugs
        actual_source = new_slug_mapping.get(edge.source, edge.source)
        actual_target = new_slug_mapping.get(edge.target, edge.target)
        result.valid_edges.append(ExtractedEdge(
            source=actual_source,
            target=actual_target,
            edge_type=edge.edge_type,
            confidence=edge.confidence,
            rationale=edge.rationale,
        ))

    # Include LLM-reported duplicates
    result.skipped_duplicates.extend(parsed.duplicates)

    return result


def write_artifacts(validated: ValidationResult, dry_run: bool = False) -> dict:
    """Write validated artifacts to disk."""
    results = {
        'created_doxai': [],
        'created_evidence': [],
        'created_edges': [],
        'skipped': validated.skipped_duplicates,
        'suggested_links': validated.suggested_links,
        'errors': validated.errors,
    }

    if dry_run:
        results['created_doxai'] = [slug for slug, _ in validated.valid_doxai]
        results['created_evidence'] = [slug for slug, _ in validated.valid_evidence]
        results['created_edges'] = validated.valid_edges
        return results

    # Write doxai
    DOXAI_DIR.mkdir(parents=True, exist_ok=True)
    for slug, content in validated.valid_doxai:
        path = DOXAI_DIR / f"{slug}.md"
        path.write_text(content)
        results['created_doxai'].append(slug)

    # Write evidence
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    for slug, content in validated.valid_evidence:
        path = EVIDENCE_DIR / f"{slug}.md"
        path.write_text(content)
        results['created_evidence'].append(slug)

    # Add edges to logos.yaml
    if validated.valid_edges:
        logos = yaml.safe_load(LOGOS_FILE.read_text()) if LOGOS_FILE.exists() else {}
        edges = logos.get('edges', [])

        for extracted in validated.valid_edges:
            edge = {
                'source': extracted.source,
                'target': extracted.target,
                'type': extracted.edge_type,
                'strength': 'moderate',
                'confidence': extracted.confidence,
            }
            if extracted.rationale:
                edge['rationale'] = extracted.rationale
            edge['provenance'] = {'method': 'extraction'}
            edge['created'] = date.today().isoformat()
            edges.append(edge)

        logos['edges'] = edges
        write_logos(logos)
        results['created_edges'] = [(e.source, e.target, e.edge_type) for e in validated.valid_edges]

    # Add suggested links from dedup (skip if already in edges)
    if validated.suggested_links and not dry_run:
        logos = yaml.safe_load(LOGOS_FILE.read_text()) if LOGOS_FILE.exists() else {}
        edges = logos.get('edges', [])

        # Build set of existing edge keys
        existing_keys = set()
        for e in edges:
            if isinstance(e, dict):
                existing_keys.add((e.get('source'), e.get('target'), e.get('type')))
            elif isinstance(e, list) and len(e) >= 3:
                existing_keys.add((e[0], e[1], e[2]))

        for source, target, edge_type in validated.suggested_links:
            # Skip if edge already exists
            if (source, target, edge_type) in existing_keys:
                continue
            edges.append({
                'source': source,
                'target': target,
                'type': edge_type,
                'strength': 'moderate',
                'provenance': {'method': 'dedup-suggestion'},
                'created': date.today().isoformat(),
            })
            existing_keys.add((source, target, edge_type))

        logos['edges'] = edges
        write_logos(logos)

    invalidate_cache()
    return results


def extract_from_phantasia(
    phantasia_slug: str,
    focus: str | None = None,
    instructions: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Main extraction pipeline.

    Args:
        phantasia_slug: The phantasia to extract from (e.g., "p-my-source")
        focus: Optional focus areas to emphasize
        instructions: Optional custom instructions
        dry_run: If True, validate but don't write files

    Returns:
        Dictionary with created artifacts and any errors
    """
    # Load phantasia
    phantasia_path = PHANTASIAI_DIR / f"{phantasia_slug}.md"
    if not phantasia_path.exists():
        raise FileNotFoundError(f"Phantasia not found: {phantasia_path}")

    phantasia = frontmatter.load(phantasia_path)

    # Resolve full content (follows file references)
    resolved_content = resolve_phantasia_content(phantasia)

    # Get existing beliefs for dedup
    existing_beliefs = get_existing_beliefs()
    today = date.today().isoformat()

    # Check if we need chunked extraction
    chunks = chunk_content(resolved_content)
    total_chunks = len(chunks)

    all_parsed = ExtractionResult()

    for chunk_num, chunk_text in chunks:
        # Build chunk-specific prompt
        chunk_header = ""
        if total_chunks > 1:
            chunk_header = f"\n\n**Note:** This is chunk {chunk_num} of {total_chunks}. Extract beliefs from THIS chunk only.\n\n"

        prompt = load_prompt(
            "extract",
            phantasia_title=phantasia.get("title", phantasia_slug),
            phantasia_source=phantasia.get("source", "Unknown"),
            phantasia_date=phantasia.get("encountered", today),
            phantasia_content=chunk_header + chunk_text,
            phantasia_slug=phantasia_slug,
            existing_beliefs=existing_beliefs,
            today=today,
            tags="",
            confidence="medium",
            evidence_type="empirical | theoretical | anecdotal | expert-opinion | logical",
            evidence_strength="strong | moderate | weak",
        )

        # Add optional focus/instructions
        if focus:
            prompt += f"\n\n## FOCUS AREAS\nPrioritize extraction of beliefs related to: {focus}"
        if instructions:
            prompt += f"\n\n## ADDITIONAL INSTRUCTIONS\n{instructions}"

        # Call Gemini for this chunk
        response = call_gemini(prompt)

        # Parse response and accumulate
        parsed = parse_extraction_response(response)
        all_parsed.doxai.extend(parsed.doxai)
        all_parsed.evidence.extend(parsed.evidence)
        all_parsed.edges.extend(parsed.edges)
        all_parsed.duplicates.extend(parsed.duplicates)

        # Update existing beliefs with newly extracted ones for cross-chunk dedup
        for doxa_content in parsed.doxai:
            try:
                post = frontmatter.loads(doxa_content)
                belief = post.get("belief", "")
                slug = f"d-{generate_slug(belief)}"
                if belief:
                    existing_beliefs += f"\n- {slug}: \"{belief}\""
            except Exception:
                pass

    # Validate all accumulated results (including dedup)
    validated = validate_extraction(all_parsed)

    # Write artifacts
    results = write_artifacts(validated, dry_run=dry_run)

    # Add chunk info to results
    results['chunks_processed'] = total_chunks

    # Update phantasia status
    if not dry_run and (results['created_doxai'] or results['created_evidence']):
        phantasia.metadata['status'] = 'processed'
        phantasia.metadata['extracted_doxai'] = results['created_doxai']
        phantasia.metadata['extracted_evidence'] = results['created_evidence']
        phantasia_path.write_text(frontmatter.dumps(phantasia))

    return results
