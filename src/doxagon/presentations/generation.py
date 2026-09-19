"""One prompt, reference, and generator path for single and batch generation.

Generating one image and generating a hundred differ only in how many specs
arrive: both build the same settings, the same assembled prompt, the same
reference closure, and the same generator invocation through the functions
below. Each finished variant is an independent, immutable, labeled asset with
its own provenance — none of them is "selected", "primary", or a display
decision, and generating never touches checkpoint order, groups, or sources.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, Sequence

from doxagon.html_editions.contracts import canonical_json, sha256

from .contracts import AssetProvenance
from .errors import WorkspaceError

PROMPT_SCHEMA = "doxagon.presentation-generation/1"
DEFAULT_GENERATOR = "image-generation/1"

RESOLUTIONS = {"1k": "1K", "2k": "2K", "4k": "4K"}
ASPECT_RATIOS = frozenset({"16:9", "9:16", "4:3", "3:2", "2:3", "1:1"})
MAX_VARIANTS = 8
# The generator accepts a bounded number of reference images. Exceeding it is
# an authoring error the caller must resolve; silently keeping the first N would
# drop a declared style reference without telling anyone.
MAX_REFERENCES = 14

# YAML reads an unquoted `16:9` as a sexagesimal duration, so a definition can
# reach this layer as an integer count of seconds. One normalizer serves every
# caller instead of a copy per entry point.
_ASPECT_FROM_SECONDS = {969: "16:9", 549: "9:16", 243: "4:3", 183: "3:2", 123: "2:3"}


def normalize_aspect_ratio(raw: Any) -> str:
    if isinstance(raw, int) and not isinstance(raw, bool) and raw in _ASPECT_FROM_SECONDS:
        return _ASPECT_FROM_SECONDS[raw]
    return str(raw)


@dataclass(frozen=True)
class GenerationSettings:
    """The resolution, framing, and variant count one generation runs with."""

    resolution: str = "2k"
    aspect_ratio: str = "16:9"
    variants: int = 3
    generator: str = DEFAULT_GENERATOR

    def __post_init__(self) -> None:
        if self.resolution not in RESOLUTIONS:
            raise WorkspaceError("PRES_GENERATION_INVALID", f"resolution {self.resolution!r} is not supported")
        if self.aspect_ratio not in ASPECT_RATIOS:
            raise WorkspaceError("PRES_GENERATION_INVALID", f"aspect ratio {self.aspect_ratio!r} is not supported")
        if not isinstance(self.variants, int) or isinstance(self.variants, bool) or not 1 <= self.variants <= MAX_VARIANTS:
            raise WorkspaceError("PRES_GENERATION_INVALID", f"variants must be 1..{MAX_VARIANTS}")
        if not self.generator:
            raise WorkspaceError("PRES_GENERATION_INVALID", "a generator identifier is required")

    @classmethod
    def resolve(
        cls, defaults: Mapping[str, Any] | None = None, overrides: Mapping[str, Any] | None = None
    ) -> "GenerationSettings":
        """Merge request overrides over authored defaults, for every caller.

        Single and batch generation resolve settings here and nowhere else, so
        one request cannot honour an authored default the other ignores.
        """

        merged: dict[str, Any] = {}
        for source in (defaults or {}, overrides or {}):
            for key in ("resolution", "aspect_ratio", "variants", "generator"):
                value = source.get(key)
                if value is not None:
                    merged[key] = value
        if "resolution" in merged:
            merged["resolution"] = str(merged["resolution"]).lower()
        if "aspect_ratio" in merged:
            merged["aspect_ratio"] = normalize_aspect_ratio(merged["aspect_ratio"])
        return cls(**merged)

    @property
    def api_resolution(self) -> str:
        return RESOLUTIONS[self.resolution]

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolution": self.resolution,
            "aspect_ratio": self.aspect_ratio,
            "variants": self.variants,
            "generator": self.generator,
        }


@dataclass(frozen=True)
class Style:
    """A reusable prompt fragment plus the reference assets it contributes."""

    style_id: str
    text: str
    references: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.style_id, "text": self.text, "references": list(self.references)}


@dataclass(frozen=True)
class GenerationSpec:
    """What one checkpoint asked to have generated."""

    checkpoint_id: str
    label: str
    alt: str
    description: str
    styles: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    settings: GenerationSettings = field(default_factory=GenerationSettings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "label": self.label,
            "alt": self.alt,
            "description": self.description,
            "styles": list(self.styles),
            "references": list(self.references),
            "settings": self.settings.as_dict(),
        }


@dataclass(frozen=True)
class AssembledPrompt:
    """The exact prompt text and reference closure sent to the generator."""

    text: str
    references: tuple[str, ...]

    @property
    def sha256(self) -> str:
        return sha256(self.text.encode("utf-8"))


def assemble_prompt(spec: GenerationSpec, styles: Mapping[str, Style]) -> AssembledPrompt:
    """Compose styles, description, and settings into one deterministic prompt."""

    sections = [f"# {spec.label}"]
    references: list[str] = []
    for style_id in spec.styles:
        style = styles.get(style_id)
        if style is None:
            raise WorkspaceError("PRES_STYLE_UNKNOWN", f"style {style_id!r} is not available", status=404)
        sections.append(f"## Style: {style.style_id}\n{style.text.strip()}")
        references.extend(reference for reference in style.references if reference not in references)
    sections.append(f"## Visual description\n{spec.description.strip()}")
    sections.append(
        "## Settings\n"
        f"- Resolution: {spec.settings.api_resolution}\n"
        f"- Aspect Ratio: {spec.settings.aspect_ratio}"
    )
    for reference in spec.references:
        if reference not in references:
            references.append(reference)
    if len(references) > MAX_REFERENCES:
        raise WorkspaceError(
            "PRES_GENERATION_REFERENCE_LIMIT",
            f"a generation may carry at most {MAX_REFERENCES} reference assets",
        )
    return AssembledPrompt("\n\n".join(sections) + "\n", tuple(references))


@dataclass(frozen=True)
class VariantPlan:
    """One independently labeled output this generation will produce."""

    checkpoint_id: str
    variant_index: int
    label: str
    alt: str
    prompt: AssembledPrompt
    settings: GenerationSettings

    def as_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "variant_index": self.variant_index,
            "label": self.label,
            "alt": self.alt,
            "prompt_sha256": self.prompt.sha256,
            "references": list(self.prompt.references),
            "settings": self.settings.as_dict(),
        }


@dataclass(frozen=True)
class GenerationPlan:
    """Every variant a request will attempt, in deterministic order."""

    schema: str
    variants: tuple[VariantPlan, ...]

    @property
    def references(self) -> tuple[str, ...]:
        ordered: list[str] = []
        for variant in self.variants:
            ordered.extend(item for item in variant.prompt.references if item not in ordered)
        return tuple(ordered)

    def as_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "variants": [variant.as_dict() for variant in self.variants]}

    @property
    def digest(self) -> str:
        return sha256(b"doxagon-presentation-plan/v1\0" + canonical_json(self.as_dict()))


def plan_generation(specs: Sequence[GenerationSpec], styles: Mapping[str, Style]) -> GenerationPlan:
    """Expand specs into variants. One spec is a batch of one, not a side path."""

    if not specs:
        raise WorkspaceError("PRES_GENERATION_INVALID", "a generation requires at least one target")
    seen: set[str] = set()
    variants: list[VariantPlan] = []
    for spec in specs:
        if spec.checkpoint_id in seen:
            raise WorkspaceError("PRES_GENERATION_INVALID", f"checkpoint {spec.checkpoint_id!r} is targeted twice")
        seen.add(spec.checkpoint_id)
        if not spec.alt.strip():
            raise WorkspaceError("PRES_GENERATION_INVALID", "a generated image requires alt text")
        prompt = assemble_prompt(spec, styles)
        for index in range(spec.settings.variants):
            variants.append(
                VariantPlan(
                    spec.checkpoint_id,
                    index,
                    f"{spec.label} — variant {index + 1}",
                    spec.alt,
                    prompt,
                    spec.settings,
                )
            )
    return GenerationPlan(PROMPT_SCHEMA, tuple(variants))


@dataclass(frozen=True)
class GeneratedImage:
    """Raw bytes a generator produced for exactly one variant."""

    data: bytes
    media_type: str = "image/png"


class GeneratorInput(Protocol):
    """Already-resolved prompt and settings, independent of rendering model."""

    prompt: AssembledPrompt
    settings: GenerationSettings


class ImageGenerator(Protocol):
    """The single seam between planning and whichever backend renders bytes."""

    def __call__(self, variant: GeneratorInput, references: Sequence[bytes]) -> GeneratedImage: ...


def generator_argv(
    executable: str,
    variant: GeneratorInput,
    prompt_file: str,
    output_directory: str,
    reference_files: Sequence[str],
) -> tuple[str, ...]:
    """The argv both entry points hand a subprocess generator, built once."""

    if len(reference_files) > MAX_REFERENCES or len(reference_files) != len(variant.prompt.references):
        raise WorkspaceError("PRES_GENERATION_REFERENCE_LIMIT", "Invocation references must exactly match the resolved closure, at most 14")
    argv = [
        executable,
        "--prompt-file",
        prompt_file,
        "--output",
        output_directory,
        "--image-size",
        variant.settings.api_resolution,
        "--aspect-ratio",
        variant.settings.aspect_ratio,
    ]
    for reference in reference_files:
        argv.extend(["--source", reference])
    return tuple(argv)


@dataclass(frozen=True)
class GeneratedOutput:
    """One produced variant, ready to be admitted as an immutable asset."""

    variant: VariantPlan
    image: GeneratedImage
    created_at: str
    # The generation this output descends from: the originating job, which a
    # retry inherits and an independently requested job never shares.
    lineage: str

    @property
    def digest(self) -> str:
        return sha256(self.image.data)

    @property
    def asset_id(self) -> str:
        # The identity is the originating generation and the variant inside it
        # *plus* the settings and bytes it produced, never the bytes alone. Two
        # independent jobs that happen to render identical pixels keep two
        # records with their own provenance, two variants of one job stay
        # independently labeled, and a retry of one lineage that reproduces a
        # variant readmits that same record instead of minting a duplicate. The
        # shared blob is deduplicated by digest underneath.
        identity = canonical_json(
            {
                "lineage": self.lineage,
                "checkpoint_id": self.variant.checkpoint_id,
                "variant_index": self.variant.variant_index,
                "prompt_sha256": self.variant.prompt.sha256,
                "settings": self.variant.settings.as_dict(),
                "sha256": self.digest,
            }
        )
        digest = sha256(b"doxagon-presentation-output/v1\0" + identity)
        return f"asset_gen_{digest[:16]}"

    def provenance(self) -> AssetProvenance:
        return AssetProvenance(
            "generated",
            self.created_at,
            self.variant.settings.generator,
            self.variant.prompt.sha256,
            f"checkpoint:{self.variant.checkpoint_id}",
            None,
        )


def execute_plan(
    plan: GenerationPlan,
    generator: ImageGenerator,
    references: Mapping[str, bytes],
    *,
    created_at: str,
    lineage: str,
) -> tuple[tuple[GeneratedOutput, ...], tuple[dict[str, Any], ...]]:
    """Run every planned variant; one variant's failure does not cancel the rest."""

    missing = [asset_id for asset_id in plan.references if asset_id not in references]
    if missing:
        raise WorkspaceError("PRES_ASSET_UNKNOWN", f"reference asset {missing[0]!r} is not in this revision", status=404)
    outputs: list[GeneratedOutput] = []
    failures: list[dict[str, Any]] = []
    for variant in plan.variants:
        reference_bytes = [references[asset_id] for asset_id in variant.prompt.references]
        try:
            image = generator(variant, reference_bytes)
        except Exception as error:  # noqa: BLE001 - a backend failure is data, not a crash
            failures.append(
                {
                    "checkpoint_id": variant.checkpoint_id,
                    "variant_index": variant.variant_index,
                    "code": "PRES_GENERATION_FAILED",
                    "message": str(error),
                }
            )
            continue
        outputs.append(GeneratedOutput(variant, image, created_at, lineage))
    return tuple(outputs), tuple(failures)


def specs_from_request(
    targets: Iterable[Mapping[str, Any]], defaults: Mapping[str, Any] | None = None
) -> tuple[GenerationSpec, ...]:
    """Build specs from request records; the batch and single routes share it."""

    specs: list[GenerationSpec] = []
    for target in targets:
        overrides = {key: target.get(key) for key in ("resolution", "aspect_ratio", "variants", "generator")}
        specs.append(
            GenerationSpec(
                str(target["checkpoint_id"]),
                str(target["label"]),
                str(target["alt"]),
                str(target["description"]),
                tuple(target.get("styles") or ()),
                tuple(target.get("references") or ()),
                GenerationSettings.resolve(defaults, overrides),
            )
        )
    return tuple(specs)
