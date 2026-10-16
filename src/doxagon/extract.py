"""Extraction: phantasia -> doxai + evidence + edges, judged by the calling agent.

`extraction_context` gives the agent the source and the graph it must fit
into. The agent writes an answer in the block format the dox-knowledge skill
documents, and `apply_extraction` validates the whole change before writing
any of it.
"""

import re
from dataclasses import dataclass, field
from datetime import date

import frontmatter

from doxagon import agent_context
from doxagon.config import DOXAI_DIR, EVIDENCE_DIR, PHANTASIAI_DIR, ROOT_DIR, SCHEMA_FILE
from doxagon.graph import invalidate_cache
from doxagon.storage import check_logos, write_logos
from doxagon.validation import GraphIntegrityError, ValidationIssue, ValidationReport


def _vault_file(reference: str):
    """Resolve a vault-relative file reference, refusing paths that leave the vault."""
    if not reference or "://" in reference:
        return None
    root = ROOT_DIR.resolve()
    candidate = (root / reference).resolve()
    if root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def resolve_phantasia_content(phantasia) -> str:
    """Resolve the full content of a phantasia, following source file references.

    If the phantasia's source field, or a `See: path` line in its body, names a
    text file inside the vault (e.g. knowledge/inbox/file.md), return that file's
    content. Otherwise return the phantasia body.
    """
    content = phantasia.content or ""
    references = [str(phantasia.get("source", ""))]
    references += [line.split("See:", 1)[1].strip().strip("`")
                   for line in content.splitlines() if line.strip().startswith("See:")]
    for reference in references:
        path = _vault_file(reference)
        if path is None:
            continue
        try:
            return path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
    return content


@dataclass
class ExtractedEdge:
    source: str
    target: str
    edge_type: str
    confidence: str = "medium"
    rationale: str = ""


@dataclass
class ExtractionResult:
    doxai: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    edges: list[ExtractedEdge] = field(default_factory=list)
    duplicates: list[dict] = field(default_factory=list)


@dataclass
class ValidationResult:
    valid_doxai: list[tuple[str, str]] = field(default_factory=list)  # (slug, content)
    valid_evidence: list[tuple[str, str]] = field(default_factory=list)
    valid_edges: list[ExtractedEdge] = field(default_factory=list)
    skipped_duplicates: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


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


def parse_extraction_response(response: str) -> ExtractionResult:
    """Parse the block-format answer into artifacts."""
    result = ExtractionResult()
    result.doxai = [m.group(1).strip() for m in re.finditer(r'===DOXA===(.*?)===END_DOXA===', response, re.DOTALL)
                    if m.group(1).strip()]
    result.evidence = [m.group(1).strip()
                       for m in re.finditer(r'===EVIDENCE===(.*?)===END_EVIDENCE===', response, re.DOTALL)
                       if m.group(1).strip()]

    # One edge per line: source|target|edge_type|confidence|rationale
    edges_match = re.search(r'===EDGES===(.*?)===END_EDGES===', response, re.DOTALL)
    for line in (edges_match.group(1).strip().split('\n') if edges_match else []):
        line = line.strip()
        if '|' not in line or line.startswith('#') or line.startswith('source'):
            continue
        parts = [part.strip() for part in line.split('|', 4)]
        if len(parts) < 3:
            continue
        levels = ("high", "medium", "low")
        confidence = parts[3] if len(parts) > 3 and parts[3] in levels else "medium"
        rationale = parts[4] if len(parts) > 4 else (parts[3] if len(parts) == 4 and parts[3] not in levels else "")
        result.edges.append(ExtractedEdge(parts[0], parts[1], parts[2], confidence, rationale))

    for match in re.finditer(r'===DUPLICATE===(.*?)===END_DUPLICATE===', response, re.DOTALL):
        dup = {}
        for line in match.group(1).strip().split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                dup[key.strip().lower()] = value.strip().strip('"')
        if dup:
            result.duplicates.append(dup)
    return result


def validate_doxa(content: str) -> tuple[bool, str, dict]:
    """Validate a single doxa artifact. Returns (valid, error_msg, metadata)."""
    try:
        post = frontmatter.loads(content)
    except Exception as e:
        return False, f"Invalid frontmatter: {e}", {}
    missing = [f for f in ('belief', 'status', 'provenance') if f not in post.metadata]
    if missing:
        return False, f"Missing required fields: {missing}", {}
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
    missing = [f for f in ('assertion', 'source', 'type', 'strength', 'status') if f not in post.metadata]
    if missing:
        return False, f"Missing required fields: {missing}", {}
    return True, "", post.metadata


def _unique_slug(prefix: str, text: str, directory, taken: set[str]) -> str:
    base = generate_slug(text)
    slug, counter = f"{prefix}{base}", 2
    while slug in taken or (directory / f"{slug}.md").exists():
        slug, counter = f"{prefix}{base}-{counter}", counter + 1
    taken.add(slug)
    return slug


def validate_extraction(parsed: ExtractionResult) -> ValidationResult:
    """Validate parsed artifacts and assign slugs; NEW:n edges resolve to them."""
    result = ValidationResult(skipped_duplicates=list(parsed.duplicates))
    taken: set[str] = set()
    for index, content in enumerate(parsed.doxai, start=1):
        valid, error, metadata = validate_doxa(content)
        if not valid:
            result.errors.append(f"doxa NEW:{index}: {error}")
            continue
        result.valid_doxai.append((_unique_slug("d-", metadata['belief'], DOXAI_DIR, taken), content))
    for index, content in enumerate(parsed.evidence, start=1):
        valid, error, metadata = validate_evidence(content)
        if not valid:
            result.errors.append(f"evidence {index}: {error}")
            continue
        result.valid_evidence.append(
            (_unique_slug("e-", metadata.get('assertion') or metadata['source'], EVIDENCE_DIR, taken), content))

    new_slugs = {f"NEW:{i}": slug for i, (slug, _) in enumerate(result.valid_doxai, start=1)}
    result.valid_edges = [
        ExtractedEdge(new_slugs.get(e.source, e.source), new_slugs.get(e.target, e.target),
                      e.edge_type, e.confidence, e.rationale)
        for e in parsed.edges
    ]
    return result


def _candidate_logos(validated: ValidationResult) -> tuple[dict, list[tuple[str, str, str]]]:
    """Merge extracted edges into the current logos and validate the whole change.

    Validation runs before any file is written, so one bad block refuses the
    whole extraction instead of leaving new doxai behind without their edges.
    """
    report = ValidationReport([ValidationIssue("invalid_artifact", error) for error in validated.errors])
    logos = agent_context.read_logos()
    today = date.today().isoformat()
    added = []
    for extracted in validated.valid_edges:
        edge = {'source': extracted.source, 'target': extracted.target, 'type': extracted.edge_type,
                'strength': 'moderate', 'confidence': extracted.confidence}
        if extracted.rationale:
            edge['rationale'] = extracted.rationale
        edge['provenance'] = {'method': 'extraction'}
        edge['created'] = today
        logos['edges'].append(edge)
        added.append(agent_context.edge_key(edge))

    if added or validated.valid_doxai:
        if not SCHEMA_FILE.exists():
            report.issues.append(ValidationIssue("schema_missing", f"{SCHEMA_FILE} is missing"))
            raise GraphIntegrityError(report)
        if added:
            report.extend(check_logos(logos, pending_doxai={slug for slug, _ in validated.valid_doxai}))
        domains = set(agent_context.vocabulary()['domains'])
        for slug, content in validated.valid_doxai:
            for tag in frontmatter.loads(content).get('tags') or []:
                if isinstance(tag, str) and tag.startswith('domain:') and tag.partition(':')[2] not in domains:
                    report.issues.append(ValidationIssue(
                        "malformed_domain",
                        f"{slug}: unregistered domain tag {tag!r}; add it to tag_prefixes.domain.values "
                        f"in {SCHEMA_FILE.name} or drop the tag"))
    if not report.valid:
        raise GraphIntegrityError(report)
    return logos, added


def write_artifacts(validated: ValidationResult, dry_run: bool = False) -> dict:
    """Validate the candidate graph, then write artifacts to disk."""
    logos, added_edges = _candidate_logos(validated)
    results = {
        'created_doxai': [slug for slug, _ in validated.valid_doxai],
        'created_evidence': [slug for slug, _ in validated.valid_evidence],
        'created_edges': added_edges,
        'skipped': validated.skipped_duplicates,
    }
    if dry_run:
        return results

    DOXAI_DIR.mkdir(parents=True, exist_ok=True)
    for slug, content in validated.valid_doxai:
        (DOXAI_DIR / f"{slug}.md").write_text(content)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    for slug, content in validated.valid_evidence:
        (EVIDENCE_DIR / f"{slug}.md").write_text(content)
    if added_edges:
        write_logos(logos)
    invalidate_cache()
    return results


def _load_phantasia(phantasia_slug: str):
    path = PHANTASIAI_DIR / f"{phantasia_slug}.md"
    if not path.exists():
        raise FileNotFoundError(f"Phantasia not found: {path}")
    return path, frontmatter.load(path)


def extraction_context(phantasia_slug: str) -> dict:
    """Return the source and the graph it must fit into, for the calling agent."""
    _, phantasia = _load_phantasia(phantasia_slug)
    metadata = {key: phantasia.get(key) for key in ('title', 'source', 'channel', 'encountered', 'tags')}
    return {
        'schema': 'doxagon.extraction-context/1',
        'phantasia': {'slug': phantasia_slug, **{k: (str(v) if k == 'encountered' and v else v)
                                                 for k, v in metadata.items()}},
        'content': resolve_phantasia_content(phantasia),
        'existing_beliefs': [{'slug': b['slug'], 'belief': b['belief']} for b in agent_context.beliefs()],
        **agent_context.vocabulary(),
        'answer_format': 'dox-knowledge skill, references/extract.md',
    }


def apply_extraction(phantasia_slug: str, response: str, dry_run: bool = False) -> dict:
    """Validate and write an extraction answer the calling agent produced."""
    path, phantasia = _load_phantasia(phantasia_slug)
    parsed = parse_extraction_response(response)
    if not (parsed.doxai or parsed.evidence or parsed.edges or parsed.duplicates):
        raise ValueError("Response has no ===DOXA===, ===EVIDENCE===, ===EDGES=== or ===DUPLICATE=== blocks")
    results = write_artifacts(validate_extraction(parsed), dry_run=dry_run)
    if not dry_run and (results['created_doxai'] or results['created_evidence']):
        phantasia.metadata['status'] = 'processed'
        phantasia.metadata['extracted_doxai'] = results['created_doxai']
        phantasia.metadata['extracted_evidence'] = results['created_evidence']
        path.write_text(frontmatter.dumps(phantasia))
    return results
