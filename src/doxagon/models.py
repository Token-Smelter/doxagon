from datetime import date
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

# Status type aliases
PhantasiaStatus = Literal["unprocessed", "processing", "processed", "archived", "abandoned", "failed"]
EvidenceStatus = Literal["provisional", "validated", "retracted", "superseded"]
EvidenceType = Literal["empirical", "theoretical", "anecdotal", "expert-opinion", "logical"]
EvidenceStrength = Literal["strong", "moderate", "weak"]
EdgeType = Literal["supports", "contradicts", "requires", "elaborates", "grounds", "causes", "resolves"]
EdgeConfidence = Literal["high", "medium", "low"]

class EvidenceRef(BaseModel):
    source: str
    quote: str | None = None
    url: str | None = None

class DoxaNode(BaseModel):
    slug: str
    title: str | None = None
    belief: str | None = None
    tags: list[str] = []
    evidence: list[EvidenceRef | dict | str] = []  # Allow dict or str slug for loose schema
    created: date | str | None = None
    updated: date | str | None = None
    path: str | None = None

    class Config:
        extra = "ignore" 

class Edge(BaseModel):
    """Lossless API representation of an annotated typed relationship."""

    model_config = ConfigDict(extra="allow")

    source: str
    target: str
    type: EdgeType
    alias: str | None = None
    rationale: str | None = None
    provenance: dict[str, Any] | None = None
    confidence: EdgeConfidence | None = None
    annotation: str | None = None
    strength: EvidenceStrength | None = None
    disputed: bool | None = None
    reviewer_notes: str | None = None
    created: date | str | None = None

class Graph(BaseModel):
    nodes: list[DoxaNode]
    edges: list[Edge]
    version: str

class DoxaDetail(DoxaNode):
    content: str
    incoming: list[Edge] = []
    outgoing: list[Edge] = []
    diegeses: list[str] = []


class DiegesisSection(BaseModel):
    """A named section within a diegesis containing doxai."""
    title: str
    doxai: list[str]


class DiegesisListItem(BaseModel):
    slug: str
    title: str
    subtitle: str | None = None
    section_count: int
    walk_count: int
    walks: list[str]  # Walk names only


class ThesisRef(BaseModel):
    """Reference to a thesis using this diegesis."""
    slug: str
    walk: str
    has_presentation: bool = False


class DiegesisDetail(BaseModel):
    slug: str
    title: str
    subtitle: str | None = None
    sections: dict[str, DiegesisSection]  # section_key -> {title, doxai[]}
    walks: dict[str, list[str]]  # walk_name -> [section_keys]
    theses: list[ThesisRef] = []
    body: str


# ============ Phantasia Models ============

class DoxaRef(BaseModel):
    """Reference to a doxa with summary info."""
    slug: str
    belief: str | None = None


class EvidenceRefSummary(BaseModel):
    """Reference to evidence with summary info."""
    slug: str
    assertion: str | None = None


class PhantasiaListItem(BaseModel):
    """Summary for list views."""
    slug: str
    title: str
    source: str
    status: PhantasiaStatus
    encountered: date | str
    doxai_count: int = 0
    evidence_count: int = 0


class PhantasiaDetail(BaseModel):
    """Full phantasia with content."""
    slug: str
    title: str
    source: str
    status: PhantasiaStatus
    encountered: date | str
    channel: str | None = None
    shared_by: str | None = None
    tags: list[str] = []
    extracted_doxai: list[DoxaRef] = []
    extracted_evidence: list[EvidenceRefSummary] = []
    content: str


class PhantasiaCreate(BaseModel):
    """Input for creating a phantasia."""
    source: str
    title: str | None = None
    channel: str | None = None
    shared_by: str | None = None
    tags: list[str] = []
    content: str | None = None


class PhantasiaUpdate(BaseModel):
    """Input for updating a phantasia."""
    status: PhantasiaStatus | None = None
    tags: list[str] | None = None
    content: str | None = None


# ============ Evidence Models ============

class EvidenceProvenance(BaseModel):
    """Provenance tracking for evidence."""
    phantasia: str | None = None
    extracted: date | str | None = None


class EvidenceListItem(BaseModel):
    """Summary for list views."""
    slug: str
    assertion: str
    source: str
    type: EvidenceType
    strength: EvidenceStrength
    status: EvidenceStatus


class EvidenceDetail(BaseModel):
    """Full evidence with content."""
    slug: str
    assertion: str
    source: str
    source_url: str | None = None
    type: EvidenceType
    strength: EvidenceStrength
    status: EvidenceStatus
    provenance: EvidenceProvenance | None = None
    annotations: list[str] = []
    gaps: list[str] = []
    content: str


class EvidenceCreate(BaseModel):
    """Input for creating evidence."""
    assertion: str
    source: str
    source_url: str | None = None
    type: EvidenceType = "empirical"
    strength: EvidenceStrength = "moderate"
    status: EvidenceStatus = "provisional"
    from_phantasia: str | None = None
    annotations: list[str] = []
    gaps: list[str] = []
    content: str | None = None


class EvidenceUpdate(BaseModel):
    """Input for updating evidence."""
    assertion: str | None = None
    source: str | None = None
    source_url: str | None = None
    type: EvidenceType | None = None
    strength: EvidenceStrength | None = None
    status: EvidenceStatus | None = None
    annotations: list[str] | None = None
    gaps: list[str] | None = None
    content: str | None = None


# ============ Edge Models ============

class EdgeProvenance(BaseModel):
    """Provenance tracking for edges."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    method: str | None = None  # extraction | integration | manual
    phantasia: str | None = None
    pass_date: str | None = Field(None, alias="pass")  # For integration passes
    audit: date | str | None = None


class EdgeListItem(BaseModel):
    """Summary for list views."""
    source: str
    target: str
    type: EdgeType
    alias: str | None = None  # Human-readable label for this specific relationship
    strength: EvidenceStrength
    confidence: EdgeConfidence = "medium"
    disputed: bool = False


class EdgeDetail(BaseModel):
    """Full edge with rationale and review metadata."""
    source: str
    target: str
    type: EdgeType
    alias: str | None = None  # Human-readable label (e.g., "is in tension with" for contradicts)
    strength: EvidenceStrength
    confidence: EdgeConfidence = "medium"
    rationale: str | None = None  # WHY this relationship exists (required for LLM edges)
    annotation: str | None = None  # Legacy field, prefer rationale
    disputed: bool = False  # Flagged for human review
    reviewer_notes: str | None = None  # Human annotations/corrections
    provenance: EdgeProvenance | None = None
    created: date | str | None = None


class EdgeCreate(BaseModel):
    """Input for creating an edge."""
    source: str
    target: str
    type: EdgeType
    alias: str | None = None  # Human-readable label for this relationship
    strength: EvidenceStrength = "moderate"
    confidence: EdgeConfidence = "medium"
    rationale: str | None = None
    annotation: str | None = None  # Legacy, prefer rationale
    disputed: bool = False
    reviewer_notes: str | None = None
    provenance: dict[str, Any] | None = None
    created: date | str | None = None
    from_phantasia: str | None = None


class EdgeUpdate(BaseModel):
    """Input for updating an edge."""
    type: EdgeType | None = None
    alias: str | None = None
    strength: EvidenceStrength | None = None
    confidence: EdgeConfidence | None = None
    rationale: str | None = None
    annotation: str | None = None
    disputed: bool | None = None
    reviewer_notes: str | None = None
    provenance: dict[str, Any] | None = None
    created: date | str | None = None


# ============ Pipeline Models ============

class PipelineStats(BaseModel):
    """Pipeline stage counts."""
    inbox_count: int
    phantasiai: dict[str, int]
    doxai_count: int
    evidence_count: int
    edges_count: int
    diegeses_count: int


class InboxItem(BaseModel):
    """An item in the inbox."""
    filename: str
    size_bytes: int
    modified: str
    ingested: bool


# ============ Doxa Creation ============

class DoxaCreate(BaseModel):
    """Input for direct doxa creation (bypasses pipeline)."""
    belief: str
    slug: str | None = None
    tags: list[str] = []
    content: str | None = None


# ============ Thesis/Presentation Models ============

class ThesisListItem(BaseModel):
    """Summary for thesis list in diegesis panel."""
    slug: str                    # e.g., "observatory"
    name: str                    # e.g., "The Observatory"
    diegesis: str               # e.g., "n-observatory"
    walk: str                   # e.g., "canonical"
    slide_count: int
    slides_with_images: int
    has_presentation: bool      # outputs/presentation/ exists
    has_essay: bool             # outputs/essay/ exists


class ThesisDetail(BaseModel):
    """Full thesis metadata for presentation viewer header."""
    slug: str
    name: str
    title: str
    subtitle: str | None = None
    diegesis: str
    walk: str
    audience: str | None = None
    description: str | None = None
    slide_count: int
    slides_with_images: int


class SlideListItem(BaseModel):
    """Summary for slide list."""
    number: int                 # e.g., 14
    slug: str                   # e.g., "14-price-collapse"
    title: str
    has_selected_image: bool
    candidate_count: int
    has_assembled_prompt: bool
    prompt_outdated: bool       # assembled_prompt.md older than definition.md
    doxai_count: int = 0        # count of linked doxai
    thumbnail_path: str | None = None  # Path to thumbnail for list display
    thumbnail_mtime: float | None = None  # Thumbnail modification time for cache-busting
    layout: str = "image"
    image_count: int = 1


class ImageCandidate(BaseModel):
    """Image candidate with thumbnail support."""
    filename: str               # e.g., "generated_20251223_144126.png"
    full: str                   # Full path: "outputs/generated_xxx.png"
    thumb: str | None = None    # Thumbnail: "outputs/.thumb_generated_xxx.png"


class ImageDefinition(BaseModel):
    """Parsed content from definition.md."""
    styles: list[str] = []
    config: dict = {}           # versions, resolution, aspect_ratio
    custom_constraints: str | None = None
    visual_description: str     # Body content


class PromptSection(BaseModel):
    """A section of the assembled prompt, grouped by source file."""
    id: str                     # Unique identifier for collapse state
    title: str                  # Display title
    source: str                 # Source file path (relative to presentation)
    scope: str                  # "global" or "local"
    section_type: str           # "constraint", "palette", "definition", "style", "settings"
    content: str                # Markdown content
    style_ref: str | None = None  # For styles: the reference from frontmatter (e.g., "diagram/base")
    provides_tag: str | None = None  # Tag this section provides (e.g., "PALETTE_CYBERNETICS")
    requires_tags: list[str] = []    # Tags this section requires


class SlideImage(BaseModel):
    """Image bundle within a slide."""
    id: str                     # e.g., "main"
    placement: str | None = None
    purpose: str | None = None
    selected: str | None = None # Path to selected image
    is_primary: bool = False    # Display bundle for image slides
    candidates: list[ImageCandidate] = []
    definition: ImageDefinition | None = None
    assembled_prompt: str | None = None
    assembled_prompt_path: str | None = None
    prompt_sections: list[PromptSection] = []


class SlideDetail(BaseModel):
    """Full slide content and metadata."""
    number: int
    slug: str
    title: str
    body: str                   # Markdown content
    speaker_notes: str = ""
    images: list[SlideImage] = []
    doxai: list[str] = []       # linked doxa slugs
    layout: str = "image"
    animation: str = "auto"
    html_content: str | None = None
    global_css: str = ""        # Global CSS from styles/html/global.css


class Annotation(BaseModel):
    """Per-slide annotation for Claude processing."""
    id: str                     # UUID
    slide_slug: str
    content: str
    created_at: str             # ISO datetime


# ============ HTML Slides Models ============

class ImageBundleCreateRequest(BaseModel):
    id: str
    purpose: str = ""


class ImageBundleCreateResponse(BaseModel):
    success: bool
    id: str


class HtmlContentRequest(BaseModel):
    content: str


class HtmlContentResponse(BaseModel):
    success: bool


class HtmlStylesRequest(BaseModel):
    content: str


class HtmlStylesResponse(BaseModel):
    success: bool


class LayoutUpdateRequest(BaseModel):
    layout: str | None = None
    animation: str | None = None


class LayoutUpdateResponse(BaseModel):
    success: bool
    layout: str
    animation: str


class SetPrimaryResponse(BaseModel):
    success: bool
    primary_id: str
