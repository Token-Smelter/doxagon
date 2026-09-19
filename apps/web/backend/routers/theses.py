"""Thesis and presentation slide endpoints for the Doxagon web UI."""

import re
import uuid
import shutil
import asyncio
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
import frontmatter
import yaml
from PIL import Image
from doxagon.config import THESES_DIR, ROOT_DIR
from doxagon.models import (
    ThesisListItem,
    ThesisDetail,
    SlideListItem,
    SlideDetail,
    SlideImage,
    ImageCandidate,
    ImageDefinition,
    PromptSection,
    Annotation,
    ImageBundleCreateRequest,
    ImageBundleCreateResponse,
    HtmlContentRequest,
    HtmlContentResponse,
    HtmlStylesRequest,
    HtmlStylesResponse,
    LayoutUpdateRequest,
    LayoutUpdateResponse,
    SetPrimaryResponse,
)
from apps.web.backend.routers.job_output import append_output, mark_complete
from doxagon.presentation_backends import provider_command, resolve_image_generator_path
from doxagon.presentations.migration import LegacyReadAdapter, is_migrated

# Image generation runs a user-owned adapter that implements the contract in
# docs/image-providers.md. The platform ships no adapter and passes no credentials.
IMAGE_GENERATOR_UNSET = (
    "No image generator configured. Set DOXAGON_IMAGE_GENERATOR to an adapter "
    "implementing docs/image-providers.md, installed in ~/.doxagon/providers/ "
    "or on PATH."
)


# Request/Response models for write operations
class ImageSelectionRequest(BaseModel):
    selected: str  # Path to selected image, e.g., "outputs/generated_xxx.png"


class ImageSelectionResponse(BaseModel):
    success: bool
    selected: str


class PromptAssemblyResponse(BaseModel):
    prompt: str
    path: str
    reference_image_count: int


class AnnotationCreateRequest(BaseModel):
    content: str


class AnnotationResponse(BaseModel):
    success: bool
    annotation: Annotation


SubmissionStatus = Literal["idle", "processing", "complete", "error"]


class SubmissionStatusResponse(BaseModel):
    status: SubmissionStatus
    message: str | None = None
    job_id: str | None = None


class SlideTextUpdateRequest(BaseModel):
    title: str | None = None
    body: str | None = None
    speaker_notes: str | None = None


class SlideTextUpdateResponse(BaseModel):
    success: bool
    updated_fields: list[str]


class ImageDefinitionUpdateRequest(BaseModel):
    custom_constraints: str | None = None
    visual_description: str | None = None


class ImageDefinitionUpdateResponse(BaseModel):
    success: bool
    updated_fields: list[str]


# Image generation models
ImageResolution = Literal["1k", "2k", "4k"]


class GenerateImageRequest(BaseModel):
    resolution: ImageResolution | None = None
    aspect_ratio: str | None = None
    versions: int | None = None


class GenerateImageResponse(BaseModel):
    success: bool
    job_id: str
    message: str


GenerationStatus = Literal["pending", "running", "complete", "error"]


class GenerateImageStatusResponse(BaseModel):
    status: GenerationStatus
    message: str | None = None
    images_generated: int = 0


# Style models
class StyleMetadata(BaseModel):
    path: str  # e.g., "blueprint/trust"
    name: str  # e.g., "Blueprint — Trust Primitives"
    tag: str | None  # e.g., "[TRUST]"
    requires: list[str]  # e.g., ["blueprint"]
    theme: str | None  # Short description
    has_sources: bool  # Whether it has reference images


class StyleListResponse(BaseModel):
    styles: list[StyleMetadata]


class StyleUpdateRequest(BaseModel):
    styles: list[str]  # List of style paths


class StyleUpdateResponse(BaseModel):
    success: bool
    styles: list[str]


class SlideCreateRequest(BaseModel):
    title: str = "New Slide"


class SlideCreateResponse(BaseModel):
    success: bool
    slug: str
    number: int


class SlideReorderRequest(BaseModel):
    slide_slugs: list[str]


class SlideReorderResponse(BaseModel):
    success: bool
    order: list[str]


class SlideUsage(BaseModel):
    thesis_slug: str
    thesis_title: str
    slide_slug: str
    slide_number: int
    slide_title: str


# In-memory job tracking
SUBMISSION_JOBS: dict[str, dict] = {}
GENERATION_JOBS: dict[str, dict] = {}


# Methods that cannot move authority. Everything else is authorship, and
# authorship over a migrated deck belongs to the checkpoint workspace.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def refuse_write_to_migrated_legacy(request: Request) -> None:
    """Confine a migrated legacy tree to the read-only compatibility window.

    Once a deck holds a verifiable promotion receipt, its authority lives in the
    revisioned checkpoint workspace. Legacy reads keep answering for the window,
    but every legacy mutation — slide creation, order, image selection, primary
    image, HTML, layout, text, generation, build — is refused through the same
    `LegacyReadAdapter` refusal, so authorship cannot fork across two systems.
    """

    if request.method in _READ_METHODS:
        return
    slug = request.path_params.get("slug")
    if not isinstance(slug, str) or not slug:
        return
    thesis_dir = THESES_DIR / slug
    if not is_migrated(thesis_dir):
        return
    LegacyReadAdapter(thesis_dir).write()


router = APIRouter(
    prefix="/theses",
    tags=["theses"],
    dependencies=[Depends(refuse_write_to_migrated_legacy)],
)

# Slug validation pattern
SLUG_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$')
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
THUMBNAIL_SIZE = (128, 72)  # 16:9 aspect ratio for thumbnails


def generate_thumbnail(image_path: Path) -> Path | None:
    """Generate a thumbnail for an image file. Returns path to thumbnail or None."""
    if not image_path.exists() or image_path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None

    thumb_path = image_path.parent / f".thumb_{image_path.stem}.jpg"

    try:
        with Image.open(image_path) as img:
            img = img.convert('RGB')
            img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            img.save(thumb_path, 'JPEG', quality=80)
        return thumb_path
    except Exception:
        return None


def ensure_thumbnails_exist(outputs_dir: Path) -> int:
    """Ensure thumbnails exist for all images in outputs directory. Returns count created."""
    if not outputs_dir.exists():
        return 0

    created = 0
    for img_file in outputs_dir.iterdir():
        if not img_file.is_file():
            continue
        if img_file.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if img_file.name.startswith('.thumb_'):
            continue

        thumb_path = img_file.parent / f".thumb_{img_file.stem}.jpg"
        if not thumb_path.exists():
            if generate_thumbnail(img_file):
                created += 1

    return created


def validate_slug(slug: str) -> bool:
    """Validate slug is safe and doesn't contain path traversal."""
    return bool(SLUG_PATTERN.match(slug)) and '..' not in slug


def safe_path(base: Path, *parts: str) -> Path:
    """Resolve path and verify it's under base directory."""
    resolved = (base / Path(*parts)).resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ValueError(f"Path escapes base directory: {resolved}")
    return resolved


def extract_number(slug: str) -> int:
    """Extract leading number from slide slug like '14-price-collapse'."""
    match = re.match(r'^(\d+)', slug)
    return int(match.group(1)) if match else 0


NUMBERED_SLIDE_DIR_PATTERN = re.compile(r"^\d+(?:-\d+)?-(.+)$")


def resolve_slide_dir(slides_dir: Path, slide_slug: str) -> Path | None:
    """Resolve a configured semantic slug or canonical directory slug safely."""
    if not validate_slug(slide_slug):
        return None

    try:
        slides_root = slides_dir.resolve()
        direct_match = safe_path(slides_root, slide_slug)
    except ValueError:
        return None

    if not slides_root.is_dir():
        return None
    if direct_match.is_dir() and direct_match.parent == slides_root:
        return direct_match

    for candidate in slides_root.iterdir():
        if not candidate.is_dir():
            continue
        try:
            candidate_dir = safe_path(slides_root, candidate.name)
        except ValueError:
            continue
        if candidate_dir.parent != slides_root:
            continue
        match = NUMBERED_SLIDE_DIR_PATTERN.match(candidate_dir.name)
        if match and match.group(1) == slide_slug:
            return candidate_dir

    return None


def count_slides(thesis_dir: Path) -> tuple[int, int]:
    """Count total slides and slides with selected images."""
    slides_dir = thesis_dir / "outputs" / "presentation" / "slides"
    if not slides_dir.exists():
        return 0, 0

    total = 0
    with_images = 0

    for slide_dir in slides_dir.iterdir():
        if not slide_dir.is_dir():
            continue
        slide_md = slide_dir / "slide.md"
        if not slide_md.exists():
            continue

        total += 1

        try:
            doc = frontmatter.load(slide_md)
            images = doc.get('images', [])
            if any(img.get('selected') for img in images if isinstance(img, dict)):
                with_images += 1
        except Exception:
            pass

    return total, with_images


def get_thesis_list_item(thesis_dir: Path, diegesis_filter: str | None = None, walk_filter: str | None = None) -> ThesisListItem | None:
    """Build ThesisListItem from thesis directory."""
    config_path = thesis_dir / "config.yaml"
    if not config_path.exists():
        return None

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except Exception:
        return None

    diegesis = config.get('diegesis', '')
    walk = config.get('walk', 'canonical')

    # Apply filters if provided
    if diegesis_filter and diegesis != diegesis_filter:
        return None
    if walk_filter and walk != walk_filter:
        return None

    slide_count, slides_with_images = count_slides(thesis_dir)

    return ThesisListItem(
        slug=thesis_dir.name,
        name=config.get('title', thesis_dir.name),
        diegesis=diegesis,
        walk=walk,
        slide_count=slide_count,
        slides_with_images=slides_with_images,
        has_presentation=(thesis_dir / "outputs" / "presentation").exists(),
        has_essay=(thesis_dir / "outputs" / "essay").exists(),
    )


@router.get("", response_model=list[ThesisListItem])
def list_theses(diegesis: str | None = None, walk: str | None = None):
    """
    List all theses, optionally filtered by diegesis and/or walk.

    Used by the diegesis panel to show linked theses.
    """
    results = []
    if not THESES_DIR.exists():
        return results

    for thesis_dir in sorted(THESES_DIR.iterdir()):
        if not thesis_dir.is_dir():
            continue
        item = get_thesis_list_item(thesis_dir, diegesis, walk)
        if item:
            results.append(item)

    return results


@router.get("/slide-usages", response_model=list[SlideUsage])
def list_slide_usages(doxa: str):
    """Return metadata for presentation slides that reference one doxa."""
    if not validate_slug(doxa):
        raise HTTPException(status_code=400, detail="Invalid doxa slug")

    usages: list[SlideUsage] = []
    if not THESES_DIR.exists():
        return usages

    for thesis_dir in sorted(THESES_DIR.iterdir(), key=lambda path: path.name):
        if not thesis_dir.is_dir():
            continue
        thesis = get_thesis_list_item(thesis_dir)
        if not thesis:
            continue

        slides_dir = thesis_dir / "outputs" / "presentation" / "slides"
        if not slides_dir.exists():
            continue

        config = {}
        config_path = thesis_dir / "outputs" / "presentation" / "config.yaml"
        if config_path.exists():
            try:
                config = yaml.safe_load(config_path.read_text()) or {}
            except Exception:
                pass

        ordered_dirs: list[tuple[int, Path]] = []
        slide_order = config.get("slide_order", []) or config.get("slides", [])
        if isinstance(slide_order, list) and slide_order:
            for number, configured_slug in enumerate(slide_order, 1):
                if not isinstance(configured_slug, str):
                    continue
                slide_dir = resolve_slide_dir(slides_dir, configured_slug)
                if slide_dir:
                    ordered_dirs.append((number, slide_dir))
        else:
            for candidate in sorted(slides_dir.iterdir(), key=lambda path: (extract_number(path.name), path.name)):
                if not candidate.is_dir():
                    continue
                slide_dir = resolve_slide_dir(slides_dir, candidate.name)
                if slide_dir:
                    ordered_dirs.append((extract_number(slide_dir.name), slide_dir))

        for number, slide_dir in ordered_dirs:
            slide_slug = slide_dir.name
            slide_md = slide_dir / "slide.md"
            if not slide_md.exists():
                continue
            try:
                doc = frontmatter.load(slide_md)
                doxai = doc.get("doxai", [])
                if not isinstance(doxai, list) or doxa not in doxai:
                    continue
                text = doc.get("text", {})
                title = text.get("title", slide_slug) if isinstance(text, dict) else slide_slug
                usages.append(SlideUsage(
                    thesis_slug=thesis.slug,
                    thesis_title=thesis.name,
                    slide_slug=slide_slug,
                    slide_number=number,
                    slide_title=title,
                ))
            except Exception:
                continue

    return usages


@router.get("/{slug}", response_model=ThesisDetail)
def get_thesis(slug: str):
    """Get full thesis detail including config and slide stats."""
    if not validate_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    if not thesis_dir.exists():
        raise HTTPException(status_code=404, detail="Thesis not found")

    config_path = thesis_dir / "config.yaml"
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Thesis config not found")

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse config: {e}")

    slide_count, slides_with_images = count_slides(thesis_dir)

    return ThesisDetail(
        slug=slug,
        name=config.get('name', slug),
        title=config.get('title', slug),
        subtitle=config.get('subtitle'),
        diegesis=config.get('diegesis', ''),
        walk=config.get('walk', 'canonical'),
        audience=config.get('audience'),
        description=config.get('description'),
        slide_count=slide_count,
        slides_with_images=slides_with_images,
    )


@router.get("/{slug}/slides", response_model=list[SlideListItem])
def list_slides(slug: str):
    """List all slides for a thesis with summary metadata."""
    if not validate_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    slides_dir = thesis_dir / "outputs" / "presentation" / "slides"
    if not slides_dir.exists():
        return []

    # Load config for ordering
    config_path = thesis_dir / "outputs" / "presentation" / "config.yaml"
    config = {}
    if config_path.exists():
        try:
            config = yaml.safe_load(config_path.read_text()) or {}
        except yaml.YAMLError:
            pass

    # Get ordered slide slugs (config-based or directory-based fallback)
    # Check both 'slide_order' (preferred) and 'slides' (legacy) fields
    slide_order = config.get('slide_order', []) or config.get('slides', [])

    results = []

    if slide_order:
        # Config-based ordering
        for slide_num, configured_slug in enumerate(slide_order, 1):
            if not isinstance(configured_slug, str):
                continue
            slide_dir = resolve_slide_dir(slides_dir, configured_slug)
            if not slide_dir:
                continue
            slide_slug = slide_dir.name

            slide_md = slide_dir / "slide.md"
            if not slide_md.exists():
                continue

            try:
                doc = frontmatter.load(slide_md)
                text = doc.get('text', {})
                images = doc.get('images', [])

                # Check image status
                has_selected = False
                candidate_count = 0
                has_assembled_prompt = False
                prompt_outdated = False
                thumbnail_path = None
                thumbnail_mtime = None

                for img in images:
                    if not isinstance(img, dict):
                        continue
                    img_id = img.get('id', 'main')
                    img_dir = slide_dir / "images" / img_id
                    outputs_dir = img_dir / "outputs"

                    # Ensure thumbnails exist (generate if missing)
                    if outputs_dir.exists():
                        ensure_thumbnails_exist(outputs_dir)

                    selected_path = img.get('selected')
                    if selected_path:
                        has_selected = True
                        # Compute thumbnail path for selected image
                        if not thumbnail_path:
                            selected_file = img_dir / selected_path
                            if selected_file.exists():
                                thumb_file = selected_file.parent / f".thumb_{selected_file.stem}.jpg"
                                # Generate thumbnail if missing
                                if not thumb_file.exists():
                                    generate_thumbnail(selected_file)
                                if thumb_file.exists():
                                    thumbnail_path = f"{slide_slug}/images/{img_id}/{thumb_file.relative_to(img_dir)}"
                                    thumbnail_mtime = thumb_file.stat().st_mtime

                    # Count candidates (exclude thumbnails)
                    if outputs_dir.exists():
                        candidates = [f for f in outputs_dir.iterdir()
                                      if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
                                      and not f.name.startswith('.thumb_')]
                        candidate_count += len(candidates)

                        # If no selected thumbnail yet, use most recent candidate's thumbnail
                        if not thumbnail_path and candidates:
                            candidates_sorted = sorted(candidates, key=lambda x: x.stat().st_mtime, reverse=True)
                            if candidates_sorted:
                                most_recent = candidates_sorted[0]
                                thumb_file = most_recent.parent / f".thumb_{most_recent.stem}.jpg"
                                # Generate thumbnail if missing
                                if not thumb_file.exists():
                                    generate_thumbnail(most_recent)
                                if thumb_file.exists():
                                    thumbnail_path = f"{slide_slug}/images/{img_id}/{thumb_file.relative_to(img_dir)}"
                                    thumbnail_mtime = thumb_file.stat().st_mtime

                        # Check assembled prompt
                        assembled_path = outputs_dir / "assembled_prompt.md"
                        if assembled_path.exists():
                            has_assembled_prompt = True

                            # Check if prompt is outdated
                            definition_path = img_dir / "definition.md"
                            if definition_path.exists():
                                if assembled_path.stat().st_mtime < definition_path.stat().st_mtime:
                                    prompt_outdated = True

                # Extract doxai references
                doxai = doc.get('doxai', [])
                doxai_count = len(doxai) if isinstance(doxai, list) else 0

                layout = doc.get('layout', 'image')
                image_count = len([img for img in images if isinstance(img, dict)])

                results.append(SlideListItem(
                    number=slide_num,  # Position in config
                    slug=slide_slug,
                    title=text.get('title', slide_slug),
                    has_selected_image=has_selected,
                    candidate_count=candidate_count,
                    has_assembled_prompt=has_assembled_prompt,
                    prompt_outdated=prompt_outdated,
                    doxai_count=doxai_count,
                    thumbnail_path=thumbnail_path,
                    thumbnail_mtime=thumbnail_mtime,
                    layout=layout,
                    image_count=image_count,
                ))
            except Exception:
                # Skip malformed slides
                pass
    else:
        # Fallback: directory-based ordering (backward compat)
        for candidate in sorted(slides_dir.iterdir()):
            if not candidate.is_dir():
                continue
            slide_dir = resolve_slide_dir(slides_dir, candidate.name)
            if not slide_dir:
                continue

            slide_md = slide_dir / "slide.md"
            if not slide_md.exists():
                continue

            try:
                doc = frontmatter.load(slide_md)
                text = doc.get('text', {})
                images = doc.get('images', [])

                # Check image status
                has_selected = False
                candidate_count = 0
                has_assembled_prompt = False
                prompt_outdated = False
                thumbnail_path = None
                dir_slug = slide_dir.name

                for img in images:
                    if not isinstance(img, dict):
                        continue
                    img_id = img.get('id', 'main')
                    img_dir = slide_dir / "images" / img_id

                    selected_path = img.get('selected')
                    if selected_path:
                        has_selected = True
                        # Compute thumbnail path for selected image
                        if not thumbnail_path:
                            selected_file = img_dir / selected_path
                            if selected_file.exists():
                                thumb_file = selected_file.parent / f".thumb_{selected_file.stem}.jpg"
                                if thumb_file.exists():
                                    thumbnail_path = f"{dir_slug}/images/{img_id}/{thumb_file.relative_to(img_dir)}"

                    # Count candidates (exclude thumbnails)
                    outputs_dir = img_dir / "outputs"
                    if outputs_dir.exists():
                        candidates = [f for f in outputs_dir.iterdir()
                                      if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
                                      and not f.name.startswith('.thumb_')]
                        candidate_count += len(candidates)

                        # If no selected thumbnail yet, use most recent candidate's thumbnail
                        if not thumbnail_path and candidates:
                            candidates_sorted = sorted(candidates, key=lambda x: x.stat().st_mtime, reverse=True)
                            if candidates_sorted:
                                most_recent = candidates_sorted[0]
                                thumb_file = most_recent.parent / f".thumb_{most_recent.stem}.jpg"
                                if thumb_file.exists():
                                    thumbnail_path = f"{dir_slug}/images/{img_id}/{thumb_file.relative_to(img_dir)}"

                        # Check assembled prompt
                        assembled_path = outputs_dir / "assembled_prompt.md"
                        if assembled_path.exists():
                            has_assembled_prompt = True

                            # Check if prompt is outdated
                            definition_path = img_dir / "definition.md"
                            if definition_path.exists():
                                if assembled_path.stat().st_mtime < definition_path.stat().st_mtime:
                                    prompt_outdated = True

                # Extract doxai references
                doxai = doc.get('doxai', [])
                doxai_count = len(doxai) if isinstance(doxai, list) else 0

                layout = doc.get('layout', 'image')
                image_count = len([img for img in images if isinstance(img, dict)])

                results.append(SlideListItem(
                    number=extract_number(slide_dir.name),
                    slug=slide_dir.name,
                    title=text.get('title', slide_dir.name),
                    has_selected_image=has_selected,
                    candidate_count=candidate_count,
                    has_assembled_prompt=has_assembled_prompt,
                    prompt_outdated=prompt_outdated,
                    doxai_count=doxai_count,
                    thumbnail_path=thumbnail_path,
                    layout=layout,
                    image_count=image_count,
                ))
            except Exception:
                # Skip malformed slides
                pass

        # Sort by slide number
        results.sort(key=lambda s: s.number)

    return results


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '-', slug)
    slug = slug.strip('-')
    return slug or 'untitled'


@router.post("/{slug}/slides", response_model=SlideCreateResponse)
def create_slide(slug: str, request: SlideCreateRequest):
    """Create a new slide at the end of the presentation."""
    if not validate_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    if not thesis_dir.exists():
        raise HTTPException(status_code=404, detail="Thesis not found")

    slides_dir = thesis_dir / "outputs" / "presentation" / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)

    # Determine next slide number
    existing_numbers = []
    for d in slides_dir.iterdir():
        if d.is_dir():
            num = extract_number(d.name)
            if num > 0:
                existing_numbers.append(num)

    next_number = max(existing_numbers, default=0) + 1

    # Create slug from title
    title_slug = slugify(request.title)
    slide_slug = f"{next_number:02d}-{title_slug}"

    # Ensure uniqueness
    slide_dir = slides_dir / slide_slug
    counter = 1
    while slide_dir.exists():
        slide_slug = f"{next_number:02d}-{title_slug}-{counter}"
        slide_dir = slides_dir / slide_slug
        counter += 1

    # Create directory structure
    slide_dir.mkdir(parents=True)
    images_dir = slide_dir / "images" / "main"
    images_dir.mkdir(parents=True)
    (images_dir / "sources").mkdir()
    (images_dir / "outputs").mkdir()

    # Create slide.md with basic frontmatter
    slide_md = slide_dir / "slide.md"
    slide_content = f"""---
text:
  title: "{request.title}"
  body: |


speaker_notes: |


images:
  - id: main
    placement: full-bleed
    purpose: ""
---
"""
    slide_md.write_text(slide_content)

    # Create empty definition.md for the image
    definition_md = images_dir / "definition.md"
    definition_content = """---
styles: []
config:
  resolution: 2k
  aspect_ratio: "16:9"
  versions: 1
custom_constraints: |

---

"""
    definition_md.write_text(definition_content)

    return SlideCreateResponse(
        success=True,
        slug=slide_slug,
        number=next_number,
    )


@router.put("/{slug}/slides/order", response_model=SlideReorderResponse)
def reorder_slides(slug: str, request: SlideReorderRequest):
    """Reorder slides by updating the presentation config."""
    if not validate_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    if not thesis_dir.exists():
        raise HTTPException(status_code=404, detail="Thesis not found")

    slides_dir = thesis_dir / "outputs" / "presentation" / "slides"
    config_path = thesis_dir / "outputs" / "presentation" / "config.yaml"

    # Validate all slugs exist
    for slide_slug in request.slide_slugs:
        slide_dir = slides_dir / slide_slug
        if not slide_dir.exists() or not (slide_dir / "slide.md").exists():
            raise HTTPException(
                status_code=400,
                detail=f"Slide not found: {slide_slug}"
            )

    # Load existing config or create new one
    config = {}
    if config_path.exists():
        try:
            config = yaml.safe_load(config_path.read_text()) or {}
        except yaml.YAMLError as e:
            raise HTTPException(status_code=500, detail=f"Failed to parse config: {e}")

    # Update slide order
    config['slide_order'] = request.slide_slugs

    # Write updated config
    try:
        config_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save config: {e}")

    return SlideReorderResponse(
        success=True,
        order=request.slide_slugs,
    )


@router.get("/{slug}/slides/{slide_slug}", response_model=SlideDetail)
def get_slide(slug: str, slide_slug: str):
    """Get full slide detail including images, prompts, and metadata."""
    if not validate_slug(slug) or not validate_slug(slide_slug):
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    slide_dir = resolve_slide_dir(thesis_dir / "outputs" / "presentation" / "slides", slide_slug)
    if not slide_dir:
        raise HTTPException(status_code=404, detail="Slide not found")

    slide_md = slide_dir / "slide.md"
    if not slide_md.exists():
        raise HTTPException(status_code=404, detail="Slide not found")

    try:
        doc = frontmatter.load(slide_md)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse slide: {e}")

    text = doc.get('text', {})
    image_configs = doc.get('images', [])

    # Build image list with full details
    images = []
    for img_config in image_configs:
        if not isinstance(img_config, dict):
            continue

        img_id = img_config.get('id', 'main')
        img_dir = slide_dir / "images" / img_id

        # Parse definition.md if exists
        definition = None
        definition_path = img_dir / "definition.md"
        if definition_path.exists():
            try:
                def_doc = frontmatter.load(definition_path)
                config = def_doc.get('config', {})
                # Fix YAML time parsing: "16:9" becomes 969, "9:16" becomes 549, etc.
                yaml_time_to_ratio = {969: "16:9", 549: "9:16", 243: "4:3", 183: "3:2", 123: "2:3"}
                if 'aspect_ratio' in config:
                    raw = config['aspect_ratio']
                    if isinstance(raw, int) and raw in yaml_time_to_ratio:
                        config['aspect_ratio'] = yaml_time_to_ratio[raw]
                    else:
                        config['aspect_ratio'] = str(raw)
                definition = ImageDefinition(
                    styles=def_doc.get('styles', []),
                    config=config,
                    custom_constraints=def_doc.get('custom_constraints'),
                    visual_description=def_doc.content or "",
                )
            except Exception:
                pass

        # Find candidate images
        candidates = []
        outputs_dir = img_dir / "outputs"
        if outputs_dir.exists():
            for f in sorted(outputs_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS and not f.name.startswith('.thumb_'):
                    # Build relative path from slide dir
                    rel_path = f.relative_to(img_dir)
                    # Look for .thumb_{stem}.jpg (JPG thumbnails are more efficient)
                    thumb_path = f.parent / f".thumb_{f.stem}.jpg"
                    candidates.append(ImageCandidate(
                        filename=f.name,
                        full=str(rel_path),
                        thumb=str(thumb_path.relative_to(img_dir)) if thumb_path.exists() else None,
                    ))

        # Check for assembled prompt
        assembled_prompt = None
        assembled_prompt_path = None
        prompt_file = outputs_dir / "assembled_prompt.md" if outputs_dir else None
        if prompt_file and prompt_file.exists():
            assembled_prompt = prompt_file.read_text()
            assembled_prompt_path = str(prompt_file.relative_to(img_dir))

        # Build prompt sections from source files
        prompt_sections = []
        styles_dir = thesis_dir / "outputs" / "presentation" / "styles"
        if img_dir.exists() and (img_dir / "definition.md").exists():
            result = construct_prompt(img_dir, styles_dir)
            if result:
                _, _, prompt_sections = result

        images.append(SlideImage(
            id=img_id,
            placement=img_config.get('placement'),
            purpose=img_config.get('purpose'),
            selected=img_config.get('selected'),
            is_primary=img_config.get('is_primary', False),
            candidates=candidates,
            definition=definition,
            assembled_prompt=assembled_prompt,
            assembled_prompt_path=assembled_prompt_path,
            prompt_sections=prompt_sections,
        ))

    # Extract doxai references
    doxai = doc.get('doxai', [])
    if not isinstance(doxai, list):
        doxai = []

    layout = doc.get('layout', 'image')
    animation = doc.get('animation', 'auto')

    html_content = None
    slide_html_path = slide_dir / "slide.html"
    if layout == 'html' and slide_html_path.exists():
        html_content = slide_html_path.read_text()

    # Read global HTML styles
    global_css = ""
    global_css_path = thesis_dir / "outputs" / "presentation" / "styles" / "html" / "global.css"
    if global_css_path.exists():
        global_css = global_css_path.read_text()

    return SlideDetail(
        number=extract_number(slide_slug),
        slug=slide_slug,
        title=text.get('title', slide_slug),
        body=text.get('body', ''),
        speaker_notes=doc.get('speaker_notes', ''),
        images=images,
        doxai=doxai,
        layout=layout,
        animation=animation,
        html_content=html_content,
        global_css=global_css,
    )


@router.put("/{slug}/slides/{slide_slug}/images/{image_id}/selected", response_model=ImageSelectionResponse)
def set_selected_image(slug: str, slide_slug: str, image_id: str, request: ImageSelectionRequest):
    """
    Set the selected image for a slide's image bundle.

    Updates the slide.md frontmatter with the new selection.
    """
    if not validate_slug(slug) or not validate_slug(slide_slug.replace('-', '')):
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
        slide_dir = safe_path(thesis_dir / "outputs" / "presentation" / "slides", slide_slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    slide_md_path = slide_dir / "slide.md"
    if not slide_md_path.exists():
        raise HTTPException(status_code=404, detail="Slide not found")

    # Validate the selected image exists
    img_dir = slide_dir / "images" / image_id
    selected_path = img_dir / request.selected
    if not selected_path.exists():
        raise HTTPException(status_code=400, detail=f"Image not found: {request.selected}")

    # Load and update the slide.md
    try:
        doc = frontmatter.load(slide_md_path)

        # Find and update the image config
        images = doc.get('images', [])
        found = False
        for img in images:
            if isinstance(img, dict) and img.get('id') == image_id:
                img['selected'] = request.selected
                found = True
                break

        if not found:
            raise HTTPException(status_code=404, detail=f"Image bundle '{image_id}' not found in slide")

        doc['images'] = images

        # Write back to file
        with open(slide_md_path, 'w') as f:
            f.write(frontmatter.dumps(doc))

        return ImageSelectionResponse(success=True, selected=request.selected)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update slide: {e}")


@router.put("/{slug}/slides/{slide_slug}/images/{image_id}/primary", response_model=SetPrimaryResponse)
def set_primary_image(slug: str, slide_slug: str, image_id: str):
    """Set an image bundle as the display bundle (primary) for the slide."""
    if not validate_slug(slug) or not validate_slug(slide_slug.replace('-', '')):
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
        slide_dir = safe_path(thesis_dir / "outputs" / "presentation" / "slides", slide_slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    slide_md_path = slide_dir / "slide.md"
    if not slide_md_path.exists():
        raise HTTPException(status_code=404, detail="Slide not found")

    try:
        doc = frontmatter.load(slide_md_path)
        images = doc.get('images', [])

        found = False
        for img in images:
            if not isinstance(img, dict):
                continue
            if img.get('id') == image_id:
                img['is_primary'] = True
                found = True
            else:
                img.pop('is_primary', None)

        if not found:
            raise HTTPException(status_code=404, detail=f"Image bundle '{image_id}' not found in slide")

        doc['images'] = images

        with open(slide_md_path, 'w') as f:
            f.write(frontmatter.dumps(doc))

        return SetPrimaryResponse(success=True, primary_id=image_id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update slide: {e}")


DEFINITION_STARTER = """\
---
styles: []
config:
  resolution: 2k
  aspect_ratio: "16:9"
  versions: 1
custom_constraints: |

---

"""

STARTER_TEMPLATE = """\
<style>
  .slide-{slug} {{
    width: 100%;
    height: 100%;
    position: relative;
  }}
</style>

<div class="slide-{slug}">
  <img data-image-id="main" />
</div>

<script>
  const slide = dox.slide;
  // slide.steps(N);
  // slide.onStep(1, () => {{ ... }});
</script>
"""


@router.post("/{slug}/slides/{slide_slug}/images", response_model=ImageBundleCreateResponse)
def create_image_bundle(slug: str, slide_slug: str, request: ImageBundleCreateRequest):
    """Create a new image bundle for a slide."""
    if not validate_slug(slug) or not validate_slug(slide_slug.replace('-', '')):
        raise HTTPException(status_code=400, detail="Invalid slug")
    if not validate_slug(request.id):
        raise HTTPException(status_code=400, detail="Invalid image bundle ID")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
        slide_dir = safe_path(thesis_dir / "outputs" / "presentation" / "slides", slide_slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    slide_md_path = slide_dir / "slide.md"
    if not slide_md_path.exists():
        raise HTTPException(status_code=404, detail="Slide not found")

    doc = frontmatter.load(slide_md_path)
    images = doc.get('images', [])
    if any(img.get('id') == request.id for img in images if isinstance(img, dict)):
        raise HTTPException(status_code=400, detail=f"Image bundle '{request.id}' already exists")

    img_dir = slide_dir / "images" / request.id
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / "sources").mkdir(exist_ok=True)
    (img_dir / "outputs").mkdir(exist_ok=True)
    (img_dir / "definition.md").write_text(DEFINITION_STARTER)

    new_entry: dict = {'id': request.id}
    if request.purpose:
        new_entry['purpose'] = request.purpose
    images.append(new_entry)
    doc['images'] = images

    with open(slide_md_path, 'w') as f:
        f.write(frontmatter.dumps(doc))

    return ImageBundleCreateResponse(success=True, id=request.id)


@router.delete("/{slug}/slides/{slide_slug}/images/{image_id}")
def delete_image_bundle(slug: str, slide_slug: str, image_id: str):
    """Delete an image bundle from a slide."""
    if not validate_slug(slug) or not validate_slug(slide_slug.replace('-', '')):
        raise HTTPException(status_code=400, detail="Invalid slug")
    if not validate_slug(image_id):
        raise HTTPException(status_code=400, detail="Invalid image bundle ID")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
        slide_dir = safe_path(thesis_dir / "outputs" / "presentation" / "slides", slide_slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    slide_md_path = slide_dir / "slide.md"
    if not slide_md_path.exists():
        raise HTTPException(status_code=404, detail="Slide not found")

    doc = frontmatter.load(slide_md_path)
    images = doc.get('images', [])

    if len(images) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last image bundle")

    original_count = len(images)
    images = [img for img in images if not (isinstance(img, dict) and img.get('id') == image_id)]
    if len(images) == original_count:
        raise HTTPException(status_code=404, detail=f"Image bundle '{image_id}' not found")

    doc['images'] = images

    img_dir = slide_dir / "images" / image_id
    if img_dir.exists():
        shutil.rmtree(img_dir)

    with open(slide_md_path, 'w') as f:
        f.write(frontmatter.dumps(doc))

    return {"success": True, "id": image_id}


@router.put("/{slug}/slides/{slide_slug}/html", response_model=HtmlContentResponse)
def save_slide_html(slug: str, slide_slug: str, request: HtmlContentRequest):
    """Save HTML content for a slide."""
    if not validate_slug(slug) or not validate_slug(slide_slug.replace('-', '')):
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
        slide_dir = safe_path(thesis_dir / "outputs" / "presentation" / "slides", slide_slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    slide_md_path = slide_dir / "slide.md"
    if not slide_md_path.exists():
        raise HTTPException(status_code=404, detail="Slide not found")

    try:
        (slide_dir / "slide.html").write_text(request.content)
        return HtmlContentResponse(success=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write slide.html: {e}")


@router.put("/{slug}/slides/{slide_slug}/layout", response_model=LayoutUpdateResponse)
def update_slide_layout(slug: str, slide_slug: str, request: LayoutUpdateRequest):
    """Update layout and animation settings for a slide."""
    if not validate_slug(slug) or not validate_slug(slide_slug.replace('-', '')):
        raise HTTPException(status_code=400, detail="Invalid slug")

    if request.layout is not None and request.layout not in ('image', 'html'):
        raise HTTPException(status_code=400, detail="layout must be 'image' or 'html'")
    if request.animation is not None and request.animation not in ('auto', 'manual'):
        raise HTTPException(status_code=400, detail="animation must be 'auto' or 'manual'")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
        slide_dir = safe_path(thesis_dir / "outputs" / "presentation" / "slides", slide_slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    slide_md_path = slide_dir / "slide.md"
    if not slide_md_path.exists():
        raise HTTPException(status_code=404, detail="Slide not found")

    try:
        doc = frontmatter.load(slide_md_path)

        if request.layout is not None:
            doc['layout'] = request.layout
        if request.animation is not None:
            doc['animation'] = request.animation

        with open(slide_md_path, 'w') as f:
            f.write(frontmatter.dumps(doc))

        # Create starter slide.html when switching to html layout for the first time
        slide_html_path = slide_dir / "slide.html"
        if request.layout == 'html' and not slide_html_path.exists():
            starter = STARTER_TEMPLATE.format(slug=slide_slug)
            slide_html_path.write_text(starter)

        layout = doc.get('layout', 'image')
        animation = doc.get('animation', 'auto')
        return LayoutUpdateResponse(success=True, layout=layout, animation=animation)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update layout: {e}")


@router.put("/{slug}/slides/{slide_slug}/text", response_model=SlideTextUpdateResponse)
def update_slide_text(slug: str, slide_slug: str, request: SlideTextUpdateRequest):
    """
    Update slide text content (title, body, speaker_notes).

    Updates the slide.md frontmatter with the provided fields.
    Only fields that are not None will be updated.
    """
    if not validate_slug(slug) or not validate_slug(slide_slug.replace('-', '')):
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
        slide_dir = safe_path(thesis_dir / "outputs" / "presentation" / "slides", slide_slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    slide_md_path = slide_dir / "slide.md"
    if not slide_md_path.exists():
        raise HTTPException(status_code=404, detail="Slide not found")

    try:
        doc = frontmatter.load(slide_md_path)
        updated_fields = []

        # Update text fields (nested under 'text' key)
        text = doc.get('text', {})
        if not isinstance(text, dict):
            text = {}

        if request.title is not None:
            text['title'] = request.title
            updated_fields.append('title')

        if request.body is not None:
            text['body'] = request.body
            updated_fields.append('body')

        if text:
            doc['text'] = text

        # Update speaker_notes (top-level field)
        if request.speaker_notes is not None:
            doc['speaker_notes'] = request.speaker_notes
            updated_fields.append('speaker_notes')

        if not updated_fields:
            raise HTTPException(status_code=400, detail="No fields to update")

        # Write back to file
        with open(slide_md_path, 'w') as f:
            f.write(frontmatter.dumps(doc))

        return SlideTextUpdateResponse(success=True, updated_fields=updated_fields)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update slide: {e}")


@router.put("/{slug}/slides/{slide_slug}/images/{image_id}/definition", response_model=ImageDefinitionUpdateResponse)
def update_image_definition(slug: str, slide_slug: str, image_id: str, request: ImageDefinitionUpdateRequest):
    """
    Update image definition content (custom_constraints, visual_description).

    Updates the definition.md file in the image bundle.
    - custom_constraints: Updates the frontmatter field
    - visual_description: Updates the markdown body content
    """
    if not validate_slug(slug) or not validate_slug(slide_slug.replace('-', '')):
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
        slide_dir = safe_path(thesis_dir / "outputs" / "presentation" / "slides", slide_slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    definition_path = slide_dir / "images" / image_id / "definition.md"
    if not definition_path.exists():
        raise HTTPException(status_code=404, detail=f"Definition not found for image '{image_id}'")

    try:
        doc = frontmatter.load(definition_path)
        updated_fields = []

        # Update custom_constraints (frontmatter field)
        if request.custom_constraints is not None:
            doc['custom_constraints'] = request.custom_constraints
            updated_fields.append('custom_constraints')

        # Update visual_description (body content)
        if request.visual_description is not None:
            doc.content = request.visual_description
            updated_fields.append('visual_description')

        if not updated_fields:
            raise HTTPException(status_code=400, detail="No fields to update")

        # Write back to file
        with open(definition_path, 'w') as f:
            f.write(frontmatter.dumps(doc))

        return ImageDefinitionUpdateResponse(success=True, updated_fields=updated_fields)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update definition: {e}")


@router.get("/{slug}/styles", response_model=StyleListResponse)
def list_styles(slug: str):
    """
    List all available styles for a thesis presentation.

    Returns style metadata including name, tag, requirements, and theme.
    """
    if not validate_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    styles_dir = thesis_dir / "outputs" / "presentation" / "styles"
    if not styles_dir.exists():
        return StyleListResponse(styles=[])

    styles = scan_styles_directory(styles_dir)
    return StyleListResponse(styles=styles)


@router.get("/{slug}/html-styles")
def get_html_styles(slug: str):
    """Get global HTML styles for a presentation."""
    if not validate_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    styles_path = thesis_dir / "outputs" / "presentation" / "styles" / "html" / "global.css"
    if not styles_path.exists():
        return {"content": ""}
    return {"content": styles_path.read_text()}


@router.put("/{slug}/html-styles", response_model=HtmlStylesResponse)
def update_html_styles(slug: str, request: HtmlStylesRequest):
    """Update global HTML styles for a presentation."""
    if not validate_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    if not thesis_dir.exists():
        raise HTTPException(status_code=404, detail="Thesis not found")

    styles_dir = thesis_dir / "outputs" / "presentation" / "styles" / "html"
    styles_dir.mkdir(parents=True, exist_ok=True)
    (styles_dir / "global.css").write_text(request.content)
    return HtmlStylesResponse(success=True)


@router.put("/{slug}/slides/{slide_slug}/images/{image_id}/styles", response_model=StyleUpdateResponse)
def update_image_styles(slug: str, slide_slug: str, image_id: str, request: StyleUpdateRequest):
    """
    Update the styles array in an image definition.

    Replaces the entire styles list with the provided list.
    """
    if not validate_slug(slug) or not validate_slug(slide_slug.replace('-', '')):
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
        slide_dir = safe_path(thesis_dir / "outputs" / "presentation" / "slides", slide_slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    definition_path = slide_dir / "images" / image_id / "definition.md"
    if not definition_path.exists():
        raise HTTPException(status_code=404, detail=f"Definition not found for image '{image_id}'")

    try:
        doc = frontmatter.load(definition_path)
        doc['styles'] = request.styles

        # Write back to file
        with open(definition_path, 'w') as f:
            f.write(frontmatter.dumps(doc))

        return StyleUpdateResponse(success=True, styles=request.styles)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update styles: {e}")


def extract_tag(content: str) -> str | None:
    """Extract **Tag:** `[TAG_NAME]` from content."""
    import re
    match = re.search(r'\*\*Tag:\*\*\s*`\[([^\]]+)\]`', content)
    return match.group(1) if match else None


def extract_requires(content: str) -> list[str]:
    """Extract **Requires:** `[TAG_NAME]` tags from content."""
    import re
    matches = re.findall(r'\*\*Requires:\*\*\s*`\[([^\]]+)\]`', content)
    return matches


def load_style_bundle(style_path: str, styles_dir: Path) -> tuple[str, list[Path], str, str | None, list[str]]:
    """Load a style bundle (definition.md text + sources/ images + title + tag + requires)."""
    bundle_dir = styles_dir / style_path
    definition_file = bundle_dir / "definition.md"

    text_content = ""
    title = style_path.replace('/', ' / ').title()
    image_paths = []
    provides_tag = None
    requires_tags = []

    if definition_file.exists():
        doc = frontmatter.load(definition_file)
        text_content = doc.content or ""
        # Try to extract title from first heading or use path
        if text_content.startswith('#'):
            first_line = text_content.split('\n')[0]
            title = first_line.lstrip('#').strip()
        # Extract tag metadata
        provides_tag = extract_tag(text_content)
        requires_tags = extract_requires(text_content)

    sources_dir = bundle_dir / "sources"
    if sources_dir.exists():
        for img in sources_dir.iterdir():
            if img.suffix.lower() in IMAGE_EXTENSIONS:
                image_paths.append(img)

    return text_content, image_paths, title, provides_tag, requires_tags


def extract_theme(content: str) -> str | None:
    """Extract theme/visual metaphor line from style definition."""
    for line in content.split('\n'):
        line = line.strip()
        if line.startswith('**Theme:') or line.startswith('**Visual Metaphor:'):
            # Extract the text after the colon
            parts = line.split(':', 1)
            if len(parts) > 1:
                return parts[1].strip().strip('*').strip()
    return None


def extract_requires_paths(content: str) -> list[str]:
    """Extract **Requires:** style path from content (not tag format)."""
    # Match patterns like **Requires:** `blueprint` or **Requires:** blueprint base style
    matches = re.findall(r'\*\*Requires:\*\*\s*`?([a-z0-9/-]+)`?', content, re.IGNORECASE)
    # Filter out tag-style matches (those in brackets)
    return [m for m in matches if not m.startswith('[')]


def scan_styles_directory(styles_dir: Path) -> list[StyleMetadata]:
    """Scan a styles directory and return metadata for all styles."""
    styles = []

    if not styles_dir.exists():
        return styles

    def scan_dir(current_dir: Path, path_prefix: str = ""):
        for item in sorted(current_dir.iterdir()):
            if not item.is_dir():
                continue
            if item.name.startswith('.') or item.name == 'sources':
                continue

            # Build the style path
            style_path = f"{path_prefix}{item.name}" if path_prefix else item.name
            definition_file = item / "definition.md"

            if definition_file.exists():
                # Parse the definition
                try:
                    doc = frontmatter.load(definition_file)
                    content = doc.content or ""

                    # Extract title from first heading
                    name = style_path.replace('/', ' / ').replace('-', ' ').title()
                    if content.startswith('#'):
                        first_line = content.split('\n')[0]
                        name = first_line.lstrip('#').strip()
                        # Clean up "Style:" prefix
                        if name.lower().startswith('style:'):
                            name = name[6:].strip()

                    # Extract metadata
                    tag = extract_tag(content)
                    requires = extract_requires_paths(content)
                    theme = extract_theme(content)

                    # Check for source images
                    sources_dir = item / "sources"
                    has_sources = sources_dir.exists() and any(
                        f.suffix.lower() in IMAGE_EXTENSIONS for f in sources_dir.iterdir()
                    ) if sources_dir.exists() else False

                    styles.append(StyleMetadata(
                        path=style_path,
                        name=name,
                        tag=tag,
                        requires=requires,
                        theme=theme,
                        has_sources=has_sources,
                    ))
                except Exception:
                    # Skip malformed definitions
                    pass

            # Recurse into subdirectories
            scan_dir(item, f"{style_path}/")

    # Skip special directories at the root
    skip_dirs = {'constraints', 'FULL_DIAGRAM_STYLE_REFERENCE'}
    for item in sorted(styles_dir.iterdir()):
        if item.is_dir() and item.name not in skip_dirs and not item.name.startswith('.'):
            scan_dir(item, f"{item.name}/") if item.name != 'global' else scan_dir(item, "global/")
            # Also check if the root item itself has a definition
            definition_file = item / "definition.md"
            if definition_file.exists():
                try:
                    doc = frontmatter.load(definition_file)
                    content = doc.content or ""
                    name = item.name.replace('-', ' ').title()
                    if content.startswith('#'):
                        first_line = content.split('\n')[0]
                        name = first_line.lstrip('#').strip()
                        if name.lower().startswith('style:'):
                            name = name[6:].strip()

                    tag = extract_tag(content)
                    requires = extract_requires_paths(content)
                    theme = extract_theme(content)
                    sources_dir = item / "sources"
                    has_sources = sources_dir.exists() and any(
                        f.suffix.lower() in IMAGE_EXTENSIONS for f in sources_dir.iterdir()
                    ) if sources_dir.exists() else False

                    styles.insert(0, StyleMetadata(
                        path=item.name,
                        name=name,
                        tag=tag,
                        requires=requires,
                        theme=theme,
                        has_sources=has_sources,
                    ))
                except Exception:
                    pass

    return styles


def construct_prompt(image_dir: Path, styles_dir: Path) -> tuple[str, list[Path], list[PromptSection]] | None:
    """
    Constructs the full generation prompt for an image directory.
    Returns (flat_prompt, images, sections) or None if no definition.md
    """
    definition_file = image_dir / "definition.md"
    if not definition_file.exists():
        return None

    doc = frontmatter.load(definition_file)
    visual_description = doc.content or ""

    styles = doc.get('styles', [])
    custom_constraints = doc.get('custom_constraints', '')
    config = doc.get('config', {})

    # Fix YAML time parsing: "16:9" becomes 969, "9:16" becomes 549, etc.
    yaml_time_to_ratio = {969: "16:9", 549: "9:16", 243: "4:3", 183: "3:2", 123: "2:3"}
    if 'aspect_ratio' in config:
        raw = config['aspect_ratio']
        if isinstance(raw, int) and raw in yaml_time_to_ratio:
            config['aspect_ratio'] = yaml_time_to_ratio[raw]
        else:
            config['aspect_ratio'] = str(raw)

    all_text = []
    all_images = []
    sections: list[PromptSection] = []

    # Track what tags are provided by which section (for dependency resolution)
    tag_providers: dict[str, str] = {}  # tag -> section_id

    # 1. Load global constraints
    global_constraints = styles_dir / "constraints" / "layout" / "definition.md"
    constraint_tag = None
    if global_constraints.exists():
        gc_doc = frontmatter.load(global_constraints)
        content = gc_doc.content or ""
        all_text.append(f"# CONSTRAINTS (MUST NOT VIOLATE)\n\n{content}")
        # Extract title and tag from content
        title = "Layout Constraints"
        if content.startswith('#'):
            title = content.split('\n')[0].lstrip('#').strip()
        constraint_tag = extract_tag(content)
        if constraint_tag:
            tag_providers[constraint_tag] = "constraints"
        sections.append(PromptSection(
            id="constraints",
            title=title,
            source="styles/constraints/layout/definition.md",
            scope="global",
            section_type="constraint",
            content=content,
            provides_tag=constraint_tag,
        ))

    # 2. Load palette if diagram family is used
    palette_tag = None
    if any('diagram' in s for s in styles):
        palette_file = styles_dir / "global" / "palette-2025" / "definition.md"
        palette_path = "styles/global/palette-2025/definition.md"
        if not palette_file.exists():
            palette_file = styles_dir / "global" / "palette" / "definition.md"
            palette_path = "styles/global/palette/definition.md"
        if palette_file.exists():
            pal_doc = frontmatter.load(palette_file)
            content = pal_doc.content or ""
            all_text.append(f"# COLOR & DESIGN SYSTEM (MUST USE)\n\n{content}")
            # Extract title and tag
            title = "Color Palette"
            if content.startswith('#'):
                title = content.split('\n')[0].lstrip('#').strip()
            palette_tag = extract_tag(content)
            if palette_tag:
                tag_providers[palette_tag] = "palette"
            sections.append(PromptSection(
                id="palette",
                title=title,
                source=palette_path,
                scope="global",
                section_type="palette",
                content=content,
                provides_tag=palette_tag,
            ))
            # Collect palette source images
            palette_sources = palette_file.parent / "sources"
            if palette_sources.exists():
                for img in palette_sources.iterdir():
                    if img.suffix.lower() in IMAGE_EXTENSIONS:
                        all_images.append(img)

    # 3. Add image definition (local) - combines custom constraints and visual description
    image_def_path = str(definition_file.relative_to(styles_dir.parent.parent.parent))
    local_content_parts = []
    if custom_constraints:
        local_content_parts.append(f"## Custom Constraints\n\n{custom_constraints}")
        all_text.append(f"# IMAGE-SPECIFIC CONSTRAINTS\n\n{custom_constraints}")
    local_content_parts.append(f"## Visual Description\n\n{visual_description}")
    all_text.append(f"# VISUAL DESCRIPTION\n\n{visual_description}")

    # Include the styles list in the definition section content
    if styles:
        local_content_parts.append(f"## Composed Styles\n\n" + "\n".join(f"- `{s}`" for s in styles))

    sections.append(PromptSection(
        id="image-definition",
        title="Image Definition",
        source=image_def_path,
        scope="local",
        section_type="definition",
        content="\n\n".join(local_content_parts),
    ))

    # 4. Load composed styles (referenced by the definition's styles: list)
    style_texts = []
    for style_path in styles:
        text, images, title, provides_tag, requires_tags = load_style_bundle(style_path, styles_dir)
        if text:
            style_texts.append(text)
            style_id = f"style-{style_path.replace('/', '-')}"
            if provides_tag:
                tag_providers[provides_tag] = style_id
            sections.append(PromptSection(
                id=style_id,
                title=title,
                source=f"styles/{style_path}/definition.md",
                scope="global",
                section_type="style",
                content=text,
                style_ref=style_path,
                provides_tag=provides_tag,
                requires_tags=requires_tags,
            ))
        all_images.extend(images)

    if style_texts:
        all_text.append("# STYLE DEFINITIONS\n\n" + "\n\n---\n\n".join(style_texts))

    # 5. Add image-specific source images
    sources_dir = image_dir / "sources"
    if sources_dir.exists():
        for img in sources_dir.iterdir():
            if img.suffix.lower() in IMAGE_EXTENSIONS:
                all_images.append(img)

    # 6. Add generation settings
    resolution = config.get('resolution', '2k')
    aspect_ratio = config.get('aspect_ratio', '16:9')
    settings_content = f"""- Resolution: {resolution.upper()}
- Aspect Ratio: {aspect_ratio}
- Background: Pure White #FFFFFF"""
    all_text.append(f"# GENERATION SETTINGS\n\n{settings_content}")
    sections.append(PromptSection(
        id="settings",
        title="Generation Settings",
        source="(computed)",
        scope="global",
        section_type="settings",
        content=settings_content,
    ))

    # Enforce 14-image limit
    if len(all_images) > 14:
        all_images = all_images[:14]

    full_prompt = "\n\n---\n\n".join(all_text)
    return full_prompt.strip(), all_images, sections


@router.post("/{slug}/slides/{slide_slug}/images/{image_id}/assemble-prompt", response_model=PromptAssemblyResponse)
def assemble_prompt_endpoint(slug: str, slide_slug: str, image_id: str):
    """
    Assemble and save the generation prompt for an image.

    Mirrors logic from factory/scripts/generate_visuals.py
    """
    if not validate_slug(slug) or not validate_slug(slide_slug.replace('-', '')):
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
        slide_dir = safe_path(thesis_dir / "outputs" / "presentation" / "slides", slide_slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    img_dir = slide_dir / "images" / image_id
    if not img_dir.exists():
        raise HTTPException(status_code=404, detail=f"Image bundle '{image_id}' not found")

    styles_dir = thesis_dir / "outputs" / "presentation" / "styles"

    result = construct_prompt(img_dir, styles_dir)
    if result is None:
        raise HTTPException(status_code=404, detail="No definition.md found for image")

    prompt, images, sections = result

    # Write to outputs directory
    outputs_dir = img_dir / "outputs"
    outputs_dir.mkdir(exist_ok=True)
    prompt_file = outputs_dir / "assembled_prompt.md"
    prompt_file.write_text(prompt)

    return PromptAssemblyResponse(
        prompt=prompt,
        path=str(prompt_file.relative_to(img_dir)),
        reference_image_count=len(images),
    )


# ============ Annotation Helpers ============

def load_annotations(slide_dir: Path) -> list[Annotation]:
    """Load annotations from a slide's annotations.yaml."""
    annotations_file = slide_dir / "annotations.yaml"
    if not annotations_file.exists():
        return []

    try:
        data = yaml.safe_load(annotations_file.read_text())
        if not data or 'annotations' not in data:
            return []
        return [Annotation(**a) for a in data['annotations']]
    except Exception:
        return []


def save_annotations(slide_dir: Path, annotations: list[Annotation]) -> None:
    """Save annotations to a slide's annotations.yaml."""
    annotations_file = slide_dir / "annotations.yaml"
    data = {'annotations': [a.model_dump() for a in annotations]}
    annotations_file.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))


def get_slides_dir(thesis_dir: Path) -> Path:
    """Get the slides directory for a thesis."""
    return thesis_dir / "outputs" / "presentation" / "slides"


# ============ Annotation Endpoints ============

@router.get("/{slug}/annotations", response_model=list[Annotation])
def get_all_annotations(slug: str):
    """Get all annotations across all slides for a thesis."""
    if not validate_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    slides_dir = get_slides_dir(thesis_dir)
    if not slides_dir.exists():
        return []

    all_annotations = []
    for slide_dir in sorted(slides_dir.iterdir()):
        if slide_dir.is_dir() and (slide_dir / "slide.md").exists():
            annotations = load_annotations(slide_dir)
            all_annotations.extend(annotations)

    return all_annotations


@router.post("/{slug}/slides/{slide_slug}/annotations", response_model=AnnotationResponse)
def create_annotation(slug: str, slide_slug: str, request: AnnotationCreateRequest):
    """Create a new annotation for a slide."""
    if not validate_slug(slug) or not validate_slug(slide_slug.replace('-', '')):
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
        slide_dir = safe_path(thesis_dir / "outputs" / "presentation" / "slides", slide_slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    if not slide_dir.exists() or not (slide_dir / "slide.md").exists():
        raise HTTPException(status_code=404, detail="Slide not found")

    # Create new annotation
    annotation = Annotation(
        id=str(uuid.uuid4())[:8],
        slide_slug=slide_slug,
        content=request.content.strip(),
        created_at=datetime.utcnow().isoformat() + "Z",
    )

    # Load existing annotations, add new one, save
    annotations = load_annotations(slide_dir)
    annotations.append(annotation)
    save_annotations(slide_dir, annotations)

    return AnnotationResponse(success=True, annotation=annotation)


@router.delete("/{slug}/annotations/{annotation_id}")
def delete_annotation(slug: str, annotation_id: str):
    """Delete an annotation by ID (searches across all slides)."""
    if not validate_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    slides_dir = get_slides_dir(thesis_dir)
    if not slides_dir.exists():
        raise HTTPException(status_code=404, detail="No slides found")

    # Search through all slide directories
    for slide_dir in slides_dir.iterdir():
        if not slide_dir.is_dir() or not (slide_dir / "slide.md").exists():
            continue

        annotations = load_annotations(slide_dir)
        original_count = len(annotations)
        annotations = [a for a in annotations if a.id != annotation_id]

        if len(annotations) < original_count:
            # Found and removed the annotation
            if annotations:
                save_annotations(slide_dir, annotations)
            else:
                # Remove empty annotations file
                annotations_file = slide_dir / "annotations.yaml"
                if annotations_file.exists():
                    annotations_file.unlink()

            return {"success": True, "deleted": annotation_id}

    raise HTTPException(status_code=404, detail="Annotation not found")


# ============ Submission Helpers ============

def build_annotation_prompt(thesis_slug: str, all_annotations: list[Annotation]) -> str:
    """Build annotation prompt with @ file references and validation instructions."""
    # Group annotations by slide
    by_slide: dict[str, list[str]] = {}
    for ann in all_annotations:
        by_slide.setdefault(ann.slide_slug, []).append(ann.content)

    prompt_parts = [
        f"# Process Annotations for {thesis_slug}",
        "",
        f"**Thesis**: {thesis_slug}",
        f"**Total annotations**: {len(all_annotations)}",
        ""
    ]

    # Include slide content via @ references
    for slide_slug, annotations in sorted(by_slide.items()):
        # Use Path constants for consistent path construction
        slide_dir = THESES_DIR / thesis_slug / "outputs" / "presentation" / "slides" / slide_slug
        slide_path = slide_dir / "slide.md"

        prompt_parts.extend([
            f"## Slide: {slide_slug}",
            "",
            "**Slide content** (title, body, speaker notes):",
            f"@{slide_path}",
            ""
        ])

        # Include all image definition files for this slide
        images_dir = slide_dir / "images"
        if images_dir.exists():
            for img_dir in sorted(images_dir.iterdir()):
                if img_dir.is_dir():
                    definition_path = img_dir / "definition.md"
                    if definition_path.exists():
                        prompt_parts.extend([
                            f"**Visual definition** (`images/{img_dir.name}/definition.md`):",
                            f"@{definition_path}",
                            ""
                        ])

        prompt_parts.extend([
            "**Annotations to apply**:",
            *[f"- {ann}" for ann in annotations],
            ""
        ])

    # Include instructions
    styles_readme = THESES_DIR / thesis_slug / "outputs" / "presentation" / "styles" / "README.md"

    prompt_parts.extend([
        "",
        "---",
        "",
        "## Instructions",
        "",
        "### For Visual Changes (MANDATORY READING)",
        "",
        "If any annotation involves changing a slide's visual (image definition), you MUST first read:",
        f"1. `docs/SLIDE_ARCHITECTURE.md` - Architecture and schema",
        f"2. `{styles_readme}` - Presentation-specific style system",
        "",
        "Then edit the `definition.md` file following the structure:",
        "- `custom_constraints` (frontmatter): Rules, restrictions, color mandates",
        "- Body: Creative visual description with `**[STYLE_TAGS]**`",
        "",
        "Visual change indicators: 'visual', 'image', 'illustration', 'diagram', 'style', 'collage', 'color', or descriptions of what to show.",
        "",
        "### For Content Changes",
        "",
        "Edit `slide.md` directly for title, body, or speaker notes.",
        "",
        "### After All Changes",
        "",
        f"Validate: `python3 factory/scripts/validate_presentation.py --presentation {thesis_slug}`",
        "",
        "Report which files were modified and validation results.",
    ])

    return "\n".join(prompt_parts)


def clear_all_annotations(thesis_dir: Path) -> int:
    """Remove all annotations.yaml files from slide directories. Returns count cleared."""
    slides_dir = thesis_dir / "outputs" / "presentation" / "slides"
    if not slides_dir.exists():
        return 0

    count = 0
    for slide_dir in slides_dir.iterdir():
        if slide_dir.is_dir():
            annotations_file = slide_dir / "annotations.yaml"
            if annotations_file.exists():
                annotations_file.unlink()
                count += 1
    return count


def is_git_repo(path: Path) -> bool:
    """Check if path is inside a git repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=path,
        capture_output=True
    )
    return result.returncode == 0


async def run_submission_job(job_id: str, thesis_slug: str, thesis_dir: Path, all_annotations: list[Annotation]):
    """Background task to run Claude CLI and handle git operations with streaming output."""
    use_git = is_git_repo(ROOT_DIR)
    checkpoint_created = False  # Track if we created a checkpoint (for safe rollback)

    try:
        # 1. Create checkpoint commit BEFORE processing (if git available)
        # IMPORTANT: Stage ALL changes to prevent data loss on rollback
        if use_git:
            SUBMISSION_JOBS[job_id] = {"status": "processing", "message": "Creating checkpoint commit..."}
            append_output(job_id, "[STATUS] Creating git checkpoint (saving all uncommitted work)...")

            # Stage ALL changes in the repo to preserve any uncommitted work
            await asyncio.to_thread(
                subprocess.run,
                ["git", "add", "-A"],
                cwd=ROOT_DIR
            )

            # Create checkpoint commit (includes all work in progress)
            commit_result = await asyncio.to_thread(
                subprocess.run,
                ["git", "commit", "-m", f"Checkpoint before applying {len(all_annotations)} annotations"],
                cwd=ROOT_DIR,
                capture_output=True,
                text=True
            )
            # Commit may "fail" if nothing to commit - that's OK
            if commit_result.returncode == 0:
                checkpoint_created = True
                append_output(job_id, "[STATUS] Checkpoint created")
            else:
                append_output(job_id, "[STATUS] No uncommitted changes to checkpoint")

        # 2. Build prompt with @ references
        SUBMISSION_JOBS[job_id] = {"status": "processing", "message": "Building annotation prompt..."}
        append_output(job_id, "[STATUS] Building annotation prompt...")
        prompt_content = build_annotation_prompt(thesis_slug, all_annotations)
        append_output(job_id, f"[STATUS] Prompt ready ({len(prompt_content)} chars)")

        # 3. Invoke presentation-annotation-processor agent with streaming
        SUBMISSION_JOBS[job_id] = {
            "status": "processing",
            "message": f"Processing {len(all_annotations)} annotations..."
        }
        append_output(job_id, f"[STATUS] Processing {len(all_annotations)} annotation(s) with Claude...")

        # Use async subprocess for streaming output
        process = await asyncio.create_subprocess_exec(
            "claude", "-p",
            "--agent", "presentation-annotation-processor",
            "--allowedTools", "Edit,Read,Glob,Grep,Bash",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=ROOT_DIR,
        )

        # Send prompt to stdin
        process.stdin.write(prompt_content.encode())
        await process.stdin.drain()
        process.stdin.close()
        await process.stdin.wait_closed()

        # Stream output line by line
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            decoded = line.decode().rstrip()
            append_output(job_id, decoded)

        return_code = await process.wait()
        mark_complete(job_id, return_code)

        if return_code == 0:
            append_output(job_id, "[STATUS] Claude completed successfully")

            # Success - commit changes (if git available) and clear annotations
            if use_git:
                SUBMISSION_JOBS[job_id] = {"status": "processing", "message": "Committing changes..."}
                append_output(job_id, "[STATUS] Committing changes...")

                # Stage ALL changes (Claude may have modified files outside thesis dir)
                await asyncio.to_thread(
                    subprocess.run,
                    ["git", "add", "-A"],
                    cwd=ROOT_DIR
                )

                # Commit
                await asyncio.to_thread(
                    subprocess.run,
                    ["git", "commit", "-m", f"Applied {len(all_annotations)} annotations via presentation viewer"],
                    cwd=ROOT_DIR,
                    capture_output=True,
                    text=True
                )
                append_output(job_id, "[STATUS] Changes committed")

            # Clear annotations regardless of git status
            cleared = clear_all_annotations(thesis_dir)
            append_output(job_id, f"[COMPLETE] Applied {len(all_annotations)} annotations (cleared {cleared} files)")
            SUBMISSION_JOBS[job_id] = {
                "status": "complete",
                "message": f"Applied {len(all_annotations)} annotations (cleared {cleared} files)"
            }
        else:
            # Failed - discard Claude's changes but keep checkpoint
            append_output(job_id, f"[ERROR] Process exited with code {return_code}")
            if checkpoint_created:
                SUBMISSION_JOBS[job_id] = {"status": "processing", "message": "Discarding failed changes..."}
                append_output(job_id, "[STATUS] Discarding Claude's changes, keeping checkpoint...")
                await asyncio.to_thread(
                    subprocess.run,
                    ["git", "reset", "--hard", "HEAD"],  # Stay at checkpoint, discard working dir changes
                    cwd=ROOT_DIR
                )
                append_output(job_id, "[STATUS] Reverted to checkpoint state (your previous work is preserved in the checkpoint commit)")
            SUBMISSION_JOBS[job_id] = {
                "status": "error",
                "message": "Processing failed - check terminal for details"
            }

    except Exception as e:
        # Discard Claude's changes on exception, keep checkpoint
        append_output(job_id, f"[ERROR] Exception: {str(e)}")
        if checkpoint_created:
            try:
                append_output(job_id, "[STATUS] Discarding failed changes, keeping checkpoint...")
                await asyncio.to_thread(
                    subprocess.run,
                    ["git", "reset", "--hard", "HEAD"],  # Stay at checkpoint, discard working dir changes
                    cwd=ROOT_DIR
                )
                append_output(job_id, "[STATUS] Reverted to checkpoint state")
            except Exception:
                pass
        mark_complete(job_id, 1)
        SUBMISSION_JOBS[job_id] = {
            "status": "error",
            "message": f"Error: {str(e)}{' (reverted to checkpoint)' if checkpoint_created else ''}"
        }


def count_uncommitted_changes() -> int:
    """Count uncommitted files in the git working directory."""
    if not is_git_repo(ROOT_DIR):
        return 0
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return 0
    # Count non-empty lines
    return len([line for line in result.stdout.strip().split('\n') if line])


# ============ Submission Endpoints ============

@router.get("/{slug}/annotations/preflight")
def preflight_check(slug: str):
    """Check conditions before annotation submission."""
    uncommitted = count_uncommitted_changes()
    return {
        "uncommitted_changes": uncommitted,
        "warning": f"You have {uncommitted} uncommitted file(s). These will be saved in a checkpoint commit." if uncommitted > 0 else None,
        "safe_to_proceed": True  # Always allow, but warn
    }


@router.post("/{slug}/annotations/submit", response_model=SubmissionStatusResponse)
async def submit_annotations(slug: str, background_tasks: BackgroundTasks):
    """Submit annotations to Claude for processing."""
    if not validate_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    # Check for existing processing job
    for job_id, job_data in SUBMISSION_JOBS.items():
        if job_data.get("status") == "processing":
            return SubmissionStatusResponse(
                status="processing",
                message="A submission is already in progress",
                job_id=job_id
            )

    # Collect all annotations
    slides_dir = get_slides_dir(thesis_dir)
    if not slides_dir.exists():
        raise HTTPException(status_code=404, detail="No slides found")

    all_annotations = []
    for slide_dir in sorted(slides_dir.iterdir()):
        if slide_dir.is_dir() and (slide_dir / "slide.md").exists():
            all_annotations.extend(load_annotations(slide_dir))

    if not all_annotations:
        return SubmissionStatusResponse(
            status="idle",
            message="No annotations to submit"
        )

    # Create job and start background task
    job_id = str(uuid.uuid4())[:8]
    SUBMISSION_JOBS[job_id] = {"status": "processing", "message": "Starting..."}

    background_tasks.add_task(
        run_submission_job,
        job_id,
        slug,
        thesis_dir,
        all_annotations
    )

    return SubmissionStatusResponse(
        status="processing",
        message=f"Processing {len(all_annotations)} annotations...",
        job_id=job_id
    )


@router.get("/{slug}/annotations/status/{job_id}", response_model=SubmissionStatusResponse)
def get_submission_status(slug: str, job_id: str):
    """Poll for submission job status."""
    if job_id not in SUBMISSION_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = SUBMISSION_JOBS[job_id]
    return SubmissionStatusResponse(
        status=job_data.get("status", "error"),
        message=job_data.get("message"),
        job_id=job_id
    )


# ============ Image Generation ============

async def run_generation_job(
    job_id: str,
    thesis_slug: str,
    slide_slug: str,
    image_id: str,
    thesis_dir: Path,
    resolution: str,
    aspect_ratio: str,
    versions: int,
):
    """Background task to generate images using Vertex AI."""
    import os

    try:
        # Find the assembled prompt
        slide_dir = thesis_dir / "outputs" / "presentation" / "slides" / slide_slug
        img_dir = slide_dir / "images" / image_id
        outputs_dir = img_dir / "outputs"
        prompt_file = outputs_dir / "assembled_prompt.md"

        if not prompt_file.exists():
            GENERATION_JOBS[job_id] = {
                "status": "error",
                "message": "No assembled prompt found. Click 'Assemble' first.",
                "images_generated": 0
            }
            mark_complete(job_id, 1)
            return

        outputs_dir.mkdir(parents=True, exist_ok=True)

        # Map resolution to API format
        resolution_map = {"1k": "1K", "2k": "2K", "4k": "4K"}
        api_resolution = resolution_map.get(resolution.lower(), "2K")

        script_path = resolve_image_generator_path(provider_command())
        if script_path is None:
            GENERATION_JOBS[job_id] = {
                "status": "error",
                "message": IMAGE_GENERATOR_UNSET,
                "images_generated": 0
            }
            mark_complete(job_id, 1)
            return

        GENERATION_JOBS[job_id] = {"status": "running", "message": "Generating images...", "images_generated": 0}
        append_output(job_id, f"[STATUS] Starting image generation ({versions} version(s) at {api_resolution})")

        # Collect source images from definition.md and style sources
        source_images = []
        definition_file = img_dir / "definition.md"
        if definition_file.exists():
            with open(definition_file) as f:
                fm = frontmatter.load(f)
                for src in fm.get("sources", []):
                    src_path = img_dir / "sources" / src
                    if src_path.exists():
                        source_images.append(str(src_path))

        # Build the base command (script generates one image per call)
        # Call script directly - it has a shebang pointing to its own venv
        base_cmd = [
            str(script_path),
            "--prompt-file", str(prompt_file),
            "--output", str(outputs_dir),
            "--image-size", api_resolution,
            "--aspect-ratio", aspect_ratio,
        ]

        # Add source images (up to 14)
        for src in source_images[:14]:
            base_cmd.extend(["--source", src])

        # Generate multiple versions by calling script multiple times
        images_generated = 0
        failed = False

        for i in range(versions):
            append_output(job_id, f"[STATUS] Generating image {i + 1} of {versions}...")
            GENERATION_JOBS[job_id]["message"] = f"Generating image {i + 1} of {versions}..."

            process = await asyncio.create_subprocess_exec(
                *base_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1"}
            )

            # Stream output
            async for line in process.stdout:
                decoded = line.decode().rstrip()
                append_output(job_id, decoded)

            await process.wait()

            if process.returncode == 0:
                images_generated += 1
                GENERATION_JOBS[job_id]["images_generated"] = images_generated
                append_output(job_id, f"[STATUS] Image {i + 1} complete")
            else:
                append_output(job_id, f"[ERROR] Image {i + 1} failed with code {process.returncode}")
                failed = True
                break

        if not failed:
            # Count actual output files
            output_files = list(outputs_dir.glob("generated_*.png"))
            images_generated = len([f for f in output_files if f.stat().st_mtime > (datetime.now().timestamp() - 120)])

            append_output(job_id, f"[COMPLETE] Generated {images_generated} image(s)")
            mark_complete(job_id, 0)
            GENERATION_JOBS[job_id] = {
                "status": "complete",
                "message": f"Generated {images_generated} image(s)",
                "images_generated": images_generated
            }
        else:
            append_output(job_id, f"[ERROR] Generation failed")
            mark_complete(job_id, 1)
            GENERATION_JOBS[job_id] = {
                "status": "error",
                "message": f"Generation failed after {images_generated} image(s) - check terminal for details",
                "images_generated": images_generated
            }

    except Exception as e:
        append_output(job_id, f"[ERROR] {str(e)}")
        mark_complete(job_id, 1)
        GENERATION_JOBS[job_id] = {
            "status": "error",
            "message": str(e),
            "images_generated": 0
        }


@router.post("/{slug}/slides/{slide_slug}/images/{image_id}/generate", response_model=GenerateImageResponse)
async def generate_image(
    slug: str,
    slide_slug: str,
    image_id: str,
    request: GenerateImageRequest,
    background_tasks: BackgroundTasks,
):
    """Start background image generation for a slide."""
    if not validate_slug(slug) or not validate_slug(slide_slug):
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    # Verify slide and image exist
    slide_dir = thesis_dir / "outputs" / "presentation" / "slides" / slide_slug
    img_dir = slide_dir / "images" / image_id

    if not slide_dir.exists():
        raise HTTPException(status_code=404, detail=f"Slide not found: {slide_slug}")
    if not img_dir.exists():
        raise HTTPException(status_code=404, detail=f"Image bundle not found: {image_id}")

    # Get defaults from definition if not specified
    definition_file = img_dir / "definition.md"
    resolution = request.resolution or "2k"
    aspect_ratio = request.aspect_ratio or "16:9"
    versions = request.versions or 3

    # YAML interprets "16:9" as time (969 seconds). Map known values back.
    yaml_time_to_ratio = {969: "16:9", 549: "9:16", 243: "4:3", 183: "3:2", 123: "2:3"}

    if definition_file.exists():
        with open(definition_file) as f:
            fm = frontmatter.load(f)
            config = fm.get("config", {})
            if not request.resolution and config.get("resolution"):
                resolution = config["resolution"]
            if not request.aspect_ratio and config.get("aspect_ratio"):
                raw_ratio = config["aspect_ratio"]
                # Handle YAML time parsing issue
                if isinstance(raw_ratio, int) and raw_ratio in yaml_time_to_ratio:
                    aspect_ratio = yaml_time_to_ratio[raw_ratio]
                else:
                    aspect_ratio = str(raw_ratio)
            if not request.versions and config.get("versions"):
                versions = config["versions"]

    # Create job
    job_id = str(uuid.uuid4())[:8]
    GENERATION_JOBS[job_id] = {"status": "pending", "message": "Starting...", "images_generated": 0}

    background_tasks.add_task(
        run_generation_job,
        job_id,
        slug,
        slide_slug,
        image_id,
        thesis_dir,
        resolution,
        aspect_ratio,
        versions,
    )

    return GenerateImageResponse(
        success=True,
        job_id=job_id,
        message=f"Generation started ({versions} images at {resolution})"
    )


@router.get("/{slug}/generate/status/{job_id}", response_model=GenerateImageStatusResponse)
def get_generation_status(slug: str, job_id: str):
    """Poll for generation job status."""
    if job_id not in GENERATION_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = GENERATION_JOBS[job_id]
    return GenerateImageStatusResponse(
        status=job_data.get("status", "error"),
        message=job_data.get("message"),
        images_generated=job_data.get("images_generated", 0)
    )


# ============ Batch Generation ============

class BatchGenerateRequest(BaseModel):
    slide_slugs: list[str]
    image_id: str = "main"
    resolution: ImageResolution | None = None
    aspect_ratio: str | None = None
    versions: int | None = None


class BatchGenerateResponse(BaseModel):
    success: bool
    job_id: str
    message: str
    started: int
    skipped: int


class BatchGenerateStatusResponse(BaseModel):
    status: GenerationStatus
    message: str | None = None
    total: int = 0
    completed: int = 0
    failed: int = 0
    current_slide: str | None = None


# Track batch jobs separately
BATCH_GENERATION_JOBS: dict[str, dict] = {}


async def run_batch_generation_job(
    job_id: str,
    thesis_slug: str,
    thesis_dir: Path,
    slide_slugs: list[str],
    image_id: str,
    resolution: str,
    aspect_ratio: str,
    versions: int,
):
    """Background task to generate images for multiple slides sequentially."""
    import os

    total = len(slide_slugs)
    completed = 0
    failed = 0

    BATCH_GENERATION_JOBS[job_id] = {
        "status": "running",
        "message": f"Starting batch generation for {total} slides...",
        "total": total,
        "completed": 0,
        "failed": 0,
        "current_slide": None,
    }
    append_output(job_id, f"[STATUS] Batch generation started: {total} slides")

    # Map resolution to API format
    resolution_map = {"1k": "1K", "2k": "2K", "4k": "4K"}
    api_resolution = resolution_map.get(resolution.lower(), "2K")

    script_path = resolve_image_generator_path(provider_command())
    if script_path is None:
        BATCH_GENERATION_JOBS[job_id] = {
            "status": "error",
            "message": IMAGE_GENERATOR_UNSET,
            "total": total,
            "completed": 0,
            "failed": total,
            "current_slide": None,
        }
        append_output(job_id, f"[ERROR] {IMAGE_GENERATOR_UNSET}")
        mark_complete(job_id, 1)
        return

    styles_dir = thesis_dir / "outputs" / "presentation" / "styles"

    for i, slide_slug in enumerate(slide_slugs, 1):
        BATCH_GENERATION_JOBS[job_id]["current_slide"] = slide_slug
        BATCH_GENERATION_JOBS[job_id]["message"] = f"Processing slide {i}/{total}: {slide_slug}"
        append_output(job_id, f"\n[STATUS] === Slide {i}/{total}: {slide_slug} ===")

        slide_dir = thesis_dir / "outputs" / "presentation" / "slides" / slide_slug
        img_dir = slide_dir / "images" / image_id

        if not img_dir.exists():
            append_output(job_id, f"[ERROR] Image directory not found: {img_dir}")
            failed += 1
            continue

        # Step 1: Assemble prompt
        append_output(job_id, f"[STATUS] Assembling prompt...")
        result = construct_prompt(img_dir, styles_dir)
        if result is None:
            append_output(job_id, f"[ERROR] No definition.md found")
            failed += 1
            continue

        prompt, source_images, _ = result
        outputs_dir = img_dir / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = outputs_dir / "assembled_prompt.md"
        prompt_file.write_text(prompt)
        append_output(job_id, f"[STATUS] Prompt assembled ({len(source_images)} reference images)")

        # Step 2: Generate image(s)
        base_cmd = [
            str(script_path),
            "--prompt-file", str(prompt_file),
            "--output", str(outputs_dir),
            "--image-size", api_resolution,
            "--aspect-ratio", aspect_ratio,
        ]

        # Add source images (up to 14)
        for src in source_images[:14]:
            base_cmd.extend(["--source", str(src)])

        slide_images_generated = 0
        for v in range(versions):
            append_output(job_id, f"[STATUS] Generating image {v + 1}/{versions}...")

            try:
                process = await asyncio.create_subprocess_exec(
                    *base_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"}
                )

                async for line in process.stdout:
                    decoded = line.decode().rstrip()
                    append_output(job_id, decoded)

                await process.wait()

                if process.returncode == 0:
                    slide_images_generated += 1
                else:
                    append_output(job_id, f"[ERROR] Generation failed with code {process.returncode}")
                    break
            except Exception as e:
                append_output(job_id, f"[ERROR] Exception: {str(e)}")
                break

        if slide_images_generated > 0:
            completed += 1
            append_output(job_id, f"[STATUS] Completed {slide_slug}: {slide_images_generated} image(s)")
        else:
            failed += 1
            append_output(job_id, f"[ERROR] Failed to generate any images for {slide_slug}")

        BATCH_GENERATION_JOBS[job_id]["completed"] = completed
        BATCH_GENERATION_JOBS[job_id]["failed"] = failed

    # Final status
    if failed == 0:
        BATCH_GENERATION_JOBS[job_id] = {
            "status": "complete",
            "message": f"Batch complete: {completed}/{total} slides",
            "total": total,
            "completed": completed,
            "failed": failed,
            "current_slide": None,
        }
        append_output(job_id, f"\n[COMPLETE] Batch generation finished: {completed}/{total} slides successful")
        mark_complete(job_id, 0)
    else:
        BATCH_GENERATION_JOBS[job_id] = {
            "status": "complete" if completed > 0 else "error",
            "message": f"Batch complete: {completed} successful, {failed} failed",
            "total": total,
            "completed": completed,
            "failed": failed,
            "current_slide": None,
        }
        append_output(job_id, f"\n[COMPLETE] Batch generation finished: {completed} successful, {failed} failed")
        mark_complete(job_id, 0 if completed > 0 else 1)


@router.post("/{slug}/generate/batch", response_model=BatchGenerateResponse)
async def batch_generate(
    slug: str,
    request: BatchGenerateRequest,
    background_tasks: BackgroundTasks,
):
    """Start batch image generation for multiple slides."""
    if not validate_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid thesis slug")

    if not thesis_dir.exists():
        raise HTTPException(status_code=404, detail="Thesis not found")

    # Validate slide slugs
    slides_dir = thesis_dir / "outputs" / "presentation" / "slides"
    valid_slugs = []
    for slide_slug in request.slide_slugs:
        slide_dir = slides_dir / slide_slug
        if slide_dir.exists() and (slide_dir / "slide.md").exists():
            valid_slugs.append(slide_slug)

    if not valid_slugs:
        raise HTTPException(status_code=400, detail="No valid slides specified")

    # Get defaults
    resolution = request.resolution or "2k"
    aspect_ratio = request.aspect_ratio or "16:9"
    versions = request.versions or 3

    # Create batch job
    job_id = str(uuid.uuid4())[:8]
    BATCH_GENERATION_JOBS[job_id] = {
        "status": "pending",
        "message": "Starting...",
        "total": len(valid_slugs),
        "completed": 0,
        "failed": 0,
        "current_slide": None,
    }

    background_tasks.add_task(
        run_batch_generation_job,
        job_id,
        slug,
        thesis_dir,
        valid_slugs,
        request.image_id,
        resolution,
        aspect_ratio,
        versions,
    )

    skipped = len(request.slide_slugs) - len(valid_slugs)
    return BatchGenerateResponse(
        success=True,
        job_id=job_id,
        message=f"Batch generation started for {len(valid_slugs)} slides",
        started=len(valid_slugs),
        skipped=skipped,
    )


@router.get("/{slug}/generate/batch/status/{job_id}", response_model=BatchGenerateStatusResponse)
def get_batch_generation_status(slug: str, job_id: str):
    """Poll for batch generation job status."""
    if job_id not in BATCH_GENERATION_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = BATCH_GENERATION_JOBS[job_id]
    return BatchGenerateStatusResponse(
        status=job_data.get("status", "error"),
        message=job_data.get("message"),
        total=job_data.get("total", 0),
        completed=job_data.get("completed", 0),
        failed=job_data.get("failed", 0),
        current_slide=job_data.get("current_slide"),
    )


# ============ Build Presentation ============

BuildStatus = Literal["pending", "running", "complete", "error"]


class BuildRequest(BaseModel):
    verbose: bool = False
    skip_pptx: bool = False
    skip_speaker_notes: bool = False
    skip_images: bool = False
    include_style_ref: bool = False


class BuildResponse(BaseModel):
    success: bool
    job_id: str
    message: str


class BuildStatusResponse(BaseModel):
    status: BuildStatus
    message: str | None = None
    build_dir: str | None = None
    files: list[str] = []


class BuildFile(BaseModel):
    name: str
    path: str
    size_bytes: int


# In-memory build job tracking
BUILD_JOBS: dict[str, dict] = {}


async def run_build_job(
    job_id: str,
    thesis_slug: str,
    verbose: bool,
    skip_pptx: bool,
    skip_speaker_notes: bool,
    skip_images: bool,
    include_style_ref: bool,
):
    """Background task to compile presentation."""
    import os

    try:
        BUILD_JOBS[job_id] = {"status": "running", "message": "Starting build..."}
        append_output(job_id, f"[STATUS] Building presentation: {thesis_slug}")

        # Build command
        cmd = [
            "python3", "factory/scripts/compile.py",
            "--presentation", thesis_slug,
        ]
        if verbose:
            cmd.append("--verbose")
        if skip_pptx:
            cmd.append("--no-pptx")
        if skip_speaker_notes:
            cmd.append("--no-speaker-notes")
        if skip_images:
            cmd.append("--no-images")
        if include_style_ref:
            cmd.append("--include-style-ref")

        append_output(job_id, f"[STATUS] Running: {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=ROOT_DIR,
            env={**os.environ, "PYTHONUNBUFFERED": "1"}
        )

        # Stream output
        build_dir = None
        async for line in process.stdout:
            decoded = line.decode().rstrip()
            append_output(job_id, decoded)
            # Capture build directory from output
            if "Build directory:" in decoded:
                build_dir = decoded.split("Build directory:")[-1].strip()

        await process.wait()

        if process.returncode == 0:
            # Find build directory if not captured from output
            if not build_dir:
                thesis_dir = THESES_DIR / thesis_slug
                build_base = thesis_dir / "outputs" / "presentation" / "build"
                if build_base.exists():
                    builds = sorted(build_base.iterdir(), reverse=True)
                    if builds:
                        build_dir = str(builds[0])

            # List files in build directory
            files = []
            if build_dir:
                build_path = Path(build_dir)
                if build_path.exists():
                    for f in build_path.iterdir():
                        if f.is_file():
                            files.append(f.name)

            append_output(job_id, f"[COMPLETE] Build finished successfully")
            mark_complete(job_id, 0)
            BUILD_JOBS[job_id] = {
                "status": "complete",
                "message": "Build completed",
                "build_dir": build_dir,
                "files": files,
            }
        else:
            append_output(job_id, f"[ERROR] Build failed with code {process.returncode}")
            mark_complete(job_id, process.returncode)
            BUILD_JOBS[job_id] = {
                "status": "error",
                "message": f"Build failed (exit code {process.returncode})",
            }

    except Exception as e:
        append_output(job_id, f"[ERROR] {str(e)}")
        mark_complete(job_id, 1)
        BUILD_JOBS[job_id] = {
            "status": "error",
            "message": str(e),
        }


@router.post("/{slug}/build", response_model=BuildResponse)
async def build_presentation(
    slug: str,
    request: BuildRequest,
    background_tasks: BackgroundTasks,
):
    """Start a background build job for the presentation."""
    if not validate_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid slug")

    try:
        thesis_dir = safe_path(THESES_DIR, slug)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slug")

    if not thesis_dir.exists():
        raise HTTPException(status_code=404, detail="Thesis not found")

    # Check for existing running build
    for job_id, job_data in BUILD_JOBS.items():
        if job_data.get("status") == "running":
            return BuildResponse(
                success=False,
                job_id=job_id,
                message="A build is already in progress"
            )

    # Create job
    job_id = str(uuid.uuid4())[:8]
    BUILD_JOBS[job_id] = {"status": "pending", "message": "Starting..."}

    background_tasks.add_task(
        run_build_job,
        job_id,
        slug,
        request.verbose,
        request.skip_pptx,
        request.skip_speaker_notes,
        request.skip_images,
        request.include_style_ref,
    )

    options_desc = []
    if request.verbose:
        options_desc.append("verbose")
    if request.skip_pptx:
        options_desc.append("no PPTX")
    if request.skip_speaker_notes:
        options_desc.append("no notes")
    if request.skip_images:
        options_desc.append("no images")
    if request.include_style_ref:
        options_desc.append("with style ref")

    return BuildResponse(
        success=True,
        job_id=job_id,
        message=f"Build started" + (f" ({', '.join(options_desc)})" if options_desc else "")
    )


@router.get("/{slug}/build/status/{job_id}", response_model=BuildStatusResponse)
def get_build_status(slug: str, job_id: str):
    """Poll for build job status."""
    if job_id not in BUILD_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = BUILD_JOBS[job_id]
    return BuildStatusResponse(
        status=job_data.get("status", "error"),
        message=job_data.get("message"),
        build_dir=job_data.get("build_dir"),
        files=job_data.get("files", []),
    )
