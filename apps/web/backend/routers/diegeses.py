from fastapi import APIRouter, HTTPException
import frontmatter
import yaml
from doxagon.config import DIEGESES_DIR, THESES_DIR
from doxagon.models import DiegesisListItem, DiegesisDetail, DiegesisSection, ThesisRef

router = APIRouter(prefix="/diegeses", tags=["diegeses"])


def find_theses_for_diegesis(diegesis_slug: str) -> list[ThesisRef]:
    """Find all theses that reference this diegesis."""
    results = []
    if not THESES_DIR.exists():
        return results

    for thesis_dir in THESES_DIR.iterdir():
        if not thesis_dir.is_dir():
            continue
        config_path = thesis_dir / "config.yaml"
        if not config_path.exists():
            continue
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            if config.get('diegesis') == diegesis_slug:
                has_presentation = (thesis_dir / "outputs" / "presentation").exists()
                results.append(ThesisRef(
                    slug=thesis_dir.name,
                    walk=config.get('walk', 'canonical'),
                    has_presentation=has_presentation
                ))
        except Exception:
            pass
    return results


@router.get("", response_model=list[DiegesisListItem])
def list_diegeses():
    results = []
    if DIEGESES_DIR.exists():
        for f in sorted(DIEGESES_DIR.glob("n-*.md")):
            try:
                doc = frontmatter.load(f)
                sections = doc.get('sections', {})
                walks = doc.get('walks', {})

                # Handle both old format (list) and new format (dict)
                if isinstance(walks, list):
                    # Old format: walks is a flat list of doxa slugs
                    walk_names = ['canonical']
                    walk_count = 1
                else:
                    # New format: walks is a dict of named walks
                    walk_names = list(walks.keys())
                    walk_count = len(walks)

                results.append(DiegesisListItem(
                    slug=f.stem,
                    title=doc.get('title', f.stem),
                    subtitle=doc.get('subtitle'),
                    section_count=len(sections),
                    walk_count=walk_count,
                    walks=walk_names
                ))
            except Exception:
                pass
    return results


@router.get("/{slug}", response_model=DiegesisDetail)
def get_diegesis(slug: str):
    path = DIEGESES_DIR / f"{slug}.md"
    if not path.exists():
         path = DIEGESES_DIR / f"n-{slug}.md"  # Try adding prefix if missing

    if not path.exists():
        raise HTTPException(status_code=404, detail="Diegesis not found")

    doc = frontmatter.load(path)

    # Parse sections
    raw_sections = doc.get('sections', {})
    sections = {}
    for key, val in raw_sections.items():
        if isinstance(val, dict):
            sections[key] = DiegesisSection(
                title=val.get('title', key),
                doxai=val.get('doxai', [])
            )

    # Parse walks
    raw_walks = doc.get('walks', {})
    if isinstance(raw_walks, list):
        # Old format: convert flat list to canonical walk
        walks = {'canonical': raw_walks}
    else:
        # New format: walks is already a dict
        walks = raw_walks

    # Find theses using this diegesis
    theses = find_theses_for_diegesis(path.stem)

    return DiegesisDetail(
        slug=path.stem,
        title=doc.get('title', path.stem),
        subtitle=doc.get('subtitle'),
        sections=sections,
        walks=walks,
        theses=theses,
        body=doc.content
    )
