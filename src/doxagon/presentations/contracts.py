"""Closed v2 presentation authoring contracts.

A revision is an ordered, labeled set of registered atomic checkpoints.
Checkpoints — not slides, sections, DOM order, or a relative step counter — are
the sole management and navigation authority, so this schema has no `layout`,
`selected`, `is_primary`, image-bundle, `slide_index`, or `(slide, step)`
member. Groups exist only as optional organization and export metadata.

Identity reuses the established canonical JSON rule from HTML Editions
(``doxagon.html_editions.contracts.canonical_json``) so every v2 digest is
computed over compact, sorted-key, UTF-8-plus-newline bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any, Iterable, Mapping, NoReturn, Sequence

from doxagon.html_editions.contracts import canonical_json, sha256

from .errors import DiagnosticLog, PresentationError, WorkspaceError, fail

MANIFEST_SCHEMA = "doxagon.presentation/2"
REGISTRATION_SCHEMA = "doxagon.presentation-checkpoint/1"
CURSOR_SCHEMA = "doxagon.deck-cursor/2"
RECEIPT_SCHEMA = "doxagon.presentation-receipt/2"
REVISION_INPUT_SCHEMA = "doxagon.presentation-revision-input/2"

VALIDATOR_VERSION = "doxagon-presentation-validator/2"
RUNTIME_VERSION = "doxagon-presentation-runtime/2"
REVISION_DOMAIN = b"doxagon-presentation-revision/v2\0"

MANIFEST_KEY = "presentation.json"
ASSET_ROOT = "assets"
RECEIPT_ROOT = "receipts"

# The grant vocabulary is exactly what the realm broker implements — see
# `resources/runtime.js` `BROKERED_CAPABILITIES`. `network`, `storage`,
# `clipboard`, and `export` have no reachable implementation inside an
# opaque-origin `allow-scripts` realm under `default-src 'none'`, so they are
# not grantable: granting one would report "granted" for a capability nothing
# can honour. `registration.py` still scans for their host tokens, so author
# code that reaches for one is refused as ungranted rather than silently
# admitted.
CAPABILITIES = frozenset({"media", "timers", "worker"})
GROUP_KINDS = frozenset({"slide", "section"})
ASSET_MEDIA_TYPES = frozenset(
    {
        "image/png", "image/jpeg", "image/webp", "image/svg+xml", "font/woff2",
        "application/json", "text/csv", "text/css", "audio/mpeg",
    }
)

#: How a checkpoint's realm occupies its surface. `stage` is the deck default:
#: a fixed frame the host lays out. `document` gives the realm the whole page,
#: so the author's own scrolling, sticky positioning, and viewport units are
#: the real thing rather than an approximation inside a box.
CHECKPOINT_MODES = frozenset({"stage", "document"})
PROVENANCE_KINDS = frozenset({"authored", "captured", "generated", "imported"})

# Legacy vocabulary that a v2 manifest must reject rather than ignore: silently
# dropping it is how a slide/step cursor or an image-bundle selection would
# survive a migration.
LEGACY_FIELDS = frozenset(
    {
        "bundle",
        "bundle_id",
        "bundles",
        "candidates",
        "image",
        "images",
        "is_primary",
        "layout",
        "primary_image",
        "selected",
        "slide",
        "slide_html",
        "slide_index",
        "slides",
        "step",
        "step_index",
        "steps",
        "thumbnail",
    }
)

MAX_CHECKPOINTS = 1024
MAX_GROUPS = 256
MAX_STYLES = 64
MAX_ASSETS = 1024
MAX_MODULES = 32
MAX_CLAIMS = 64
MAX_CUES = 256
CLAIM_STATUSES = frozenset({"unassessed", "supported", "qualified", "contested"})
_KNOWLEDGE_ID = re.compile(r"[den]-[a-z0-9][a-z0-9-]{0,127}\Z")
MAX_STRING_CHARS = 4096
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_METADATA_BYTES = 16 * 1024

# The aggregate declared-asset budget is the one validation limit a deployment
# may choose, because it is the only one whose right value depends on the corpus
# rather than on the schema. A real vault deck declares every image candidate
# ever produced for it — the migrator preserves unreferenced variants on purpose
# — so a fixed aggregate refuses decks whose every individual asset, count,
# digest, media signature, and provenance record is valid.
DEFAULT_TOTAL_ASSET_BYTES = 512 * 1024 * 1024

# No configured budget may exceed what the unchanged per-asset and asset-count
# checks can admit at all: MAX_ASSETS records of MAX_ASSET_BYTES each is the
# largest revision this schema can describe. A number above it is not a larger
# limit, it is a request for no limit, so it is refused rather than accepted as
# one. Peak validation memory is bounded by MAX_ASSET_BYTES whatever the budget
# is — assets are read, verified, and released one at a time (`sources.read_asset`)
# — so this bound governs the total size of one revision, not process memory.
MAX_TOTAL_ASSET_BYTES_CEILING = MAX_ASSETS * MAX_ASSET_BYTES

#: The deployment variable that names the aggregate budget, in whole bytes.
TOTAL_ASSET_BYTES_ENV = "DOXAGON_PRESENTATION_MAX_TOTAL_ASSET_BYTES"

_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_WHOLE_BYTES = re.compile(r"[0-9]+\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_REVISION = re.compile(r"sha256:[a-f0-9]{64}\Z")
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,31}\Z")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z\Z")


@dataclass(frozen=True)
class ValidationPolicy:
    """The bounded validation limits one deployment may choose.

    Exactly one member is configurable, and it is bounded on both sides. Every
    other limit — per-asset bytes, asset count, containment, exact size, digest,
    media signature, provenance, atomic promotion — stays schema, not policy,
    because those answer "is this record admissible at all", which no deployment
    may relax.
    """

    total_asset_bytes: int = DEFAULT_TOTAL_ASSET_BYTES

    def __post_init__(self) -> None:
        value = self.total_asset_bytes
        # `bool` is an `int` in Python; `True` as a byte budget is a mistake, not
        # a one-byte limit.
        if isinstance(value, bool) or not isinstance(value, int):
            _refuse_policy(f"the aggregate asset budget must be a whole number of bytes, not {value!r}")
        if value < 1 or value > MAX_TOTAL_ASSET_BYTES_CEILING:
            _refuse_policy(
                f"the aggregate asset budget must be between 1 and {MAX_TOTAL_ASSET_BYTES_CEILING} bytes, not {value}"
            )


#: What a process validates with when no deployment named anything else.
DEFAULT_VALIDATION_POLICY = ValidationPolicy()


def _refuse_policy(message: str) -> NoReturn:
    # A misconfigured limit is a deployment fault, not an author's: it is refused
    # where it is read, so the process cannot start and then silently validate
    # against a limit nobody chose.
    raise WorkspaceError("PRES_ASSET_POLICY_INVALID", message, status=500)


def resolve_validation_policy(total_asset_bytes: str | None) -> ValidationPolicy:
    """Read one deployment's aggregate budget, refusing anything unreadable.

    An unset variable selects the conservative default. Anything set is taken
    literally: only whole decimal bytes are accepted, so an empty, signed,
    fractional, suffixed (`512MiB`), exponential, or hexadecimal value refuses
    instead of falling back to a limit the operator did not ask for.
    """

    if total_asset_bytes is None:
        return DEFAULT_VALIDATION_POLICY
    text = total_asset_bytes.strip()
    if _WHOLE_BYTES.match(text) is None:
        _refuse_policy(f"{TOTAL_ASSET_BYTES_ENV} must be whole decimal bytes, not {total_asset_bytes!r}")
    return ValidationPolicy(int(text))


def pointer(*tokens: object) -> str:
    """Build an RFC 6901 pointer from already-known path tokens."""

    return "".join(f"/{str(token).replace('~', '~0').replace('/', '~1')}" for token in tokens)


def child(parent: str, *tokens: object) -> str:
    return parent + pointer(*tokens)


def _duplicate_free(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("PRES_DUPLICATE_KEY", f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def parse_manifest_bytes(raw: bytes) -> dict[str, Any]:
    """Decode manifest bytes into a closed JSON object with no duplicate keys."""

    if len(raw) > MAX_MANIFEST_BYTES:
        fail("PRES_MANIFEST_INVALID_JSON", "manifest exceeds the size limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        fail("PRES_MANIFEST_INVALID_JSON", "manifest is not UTF-8")
    try:
        parsed = json.loads(text, object_pairs_hook=_duplicate_free)
    except json.JSONDecodeError as error:
        fail("PRES_MANIFEST_INVALID_JSON", f"manifest is not valid JSON: {error.msg}", "", MANIFEST_KEY, error.lineno)
    except PresentationError as error:
        # The pairs hook cannot know its own pointer; locate it by source file.
        fail(error.diagnostic.code, error.diagnostic.message, "", MANIFEST_KEY)
    return _object(parsed, "", "manifest")


def _object(value: Any, at: str, subject: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail("PRES_FIELD_INVALID", f"{subject} must be an object", at)
    if any(not isinstance(key, str) for key in value):
        fail("PRES_FIELD_INVALID", f"{subject} has a non-string key", at)
    return value


def _closed(record: Mapping[str, Any], allowed: Iterable[str], at: str, subject: str) -> None:
    legacy = sorted(set(record) & LEGACY_FIELDS)
    if legacy:
        fail(
            "PRES_LEGACY_FIELD",
            f"{subject} declares legacy field {legacy[0]!r}; checkpoints are the only navigation authority",
            child(at, legacy[0]),
        )
    unknown = sorted(set(record) - set(allowed))
    if unknown:
        fail("PRES_UNKNOWN_FIELD", f"{subject} declares unknown field {unknown[0]!r}", child(at, unknown[0]))


def _string(value: Any, at: str, subject: str) -> str:
    if not isinstance(value, str) or not value:
        fail("PRES_FIELD_INVALID", f"{subject} must be a non-empty string", at)
    if len(value) > MAX_STRING_CHARS:
        fail("PRES_FIELD_INVALID", f"{subject} exceeds the string length limit", at)
    if "\x00" in value:
        fail("PRES_FIELD_INVALID", f"{subject} contains NUL", at)
    return value


def _identifier(value: Any, at: str, subject: str) -> str:
    text = _string(value, at, subject)
    if _ID.fullmatch(text) is None:
        fail("PRES_FIELD_INVALID", f"{subject} is not a valid identifier", at)
    return text


def _digest(value: Any, at: str, subject: str) -> str:
    text = _string(value, at, subject)
    if _SHA.fullmatch(text) is None:
        fail("PRES_FIELD_INVALID", f"{subject} is not a lowercase sha256 digest", at)
    return text


def _relative_key(value: Any, at: str, subject: str) -> str:
    key = _string(value, at, subject)
    if (
        key.startswith("/")
        or "\\" in key
        or "%2f" in key.lower()
        or re.match(r"^[a-zA-Z]:", key)
        or any(part in {"", ".", ".."} for part in key.split("/"))
    ):
        fail("PRES_SOURCE_CONTAINMENT", f"{subject} is not a safe relative key", at)
    return key


def _bool(value: Any, at: str, subject: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        fail("PRES_FIELD_INVALID", f"{subject} must be a boolean", at)
    return value


def _size(value: Any, at: str, subject: str, *, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > maximum:
        fail("PRES_FIELD_INVALID", f"{subject} must be a non-negative integer within the limit", at)
    return value


def _json_value(value: Any, at: str, subject: str) -> Any:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_json_value(item, at, subject) for item in value]
    if isinstance(value, dict):
        return {_string(key, at, f"{subject} key"): _json_value(item, at, subject) for key, item in value.items()}
    fail("PRES_FIELD_INVALID", f"{subject} is not JSON-compatible", at)


def _metadata(value: Any, at: str, subject: str) -> dict[str, Any]:
    if value is None:
        return {}
    record = _object(value, at, subject)
    copied = {key: _json_value(item, at, subject) for key, item in record.items()}
    if len(canonical_json(copied)) > MAX_METADATA_BYTES:
        fail("PRES_FIELD_INVALID", f"{subject} exceeds the metadata size limit", at)
    return copied


def _unique(values: tuple[str, ...], at: str, code: str, subject: str) -> None:
    seen: set[str] = set()
    for index, value in enumerate(values):
        if value in seen:
            fail(code, f"{subject} repeats {value!r}", child(at, index))
        seen.add(value)


@dataclass(frozen=True)
class AssetProvenance:
    """Revisioned, reviewable origin metadata for immutable asset bytes."""

    kind: str
    created_at: str
    generator: str | None
    prompt_sha256: str | None
    source_ref: str | None
    license: str | None

    @classmethod
    def parse(cls, value: Any, at: str) -> "AssetProvenance":
        record = _object(value, at, "asset provenance")
        _closed(record, {"kind", "created_at", "generator", "prompt_sha256", "source_ref", "license"}, at, "asset provenance")
        kind = _string(record.get("kind"), child(at, "kind"), "provenance kind")
        if kind not in PROVENANCE_KINDS:
            fail("PRES_ASSET_PROVENANCE_INVALID", f"provenance kind {kind!r} is not supported", child(at, "kind"))
        created_at = _string(record.get("created_at"), child(at, "created_at"), "provenance created_at")
        if _TIMESTAMP.fullmatch(created_at) is None:
            fail("PRES_ASSET_PROVENANCE_INVALID", "provenance created_at must be an RFC 3339 UTC timestamp", child(at, "created_at"))
        generator = record.get("generator")
        prompt = record.get("prompt_sha256")
        if kind == "generated" and generator is None:
            fail("PRES_ASSET_PROVENANCE_INVALID", "generated provenance requires a generator", at)
        return cls(
            kind,
            created_at,
            None if generator is None else _string(generator, child(at, "generator"), "provenance generator"),
            None if prompt is None else _digest(prompt, child(at, "prompt_sha256"), "provenance prompt_sha256"),
            None if record.get("source_ref") is None else _string(record.get("source_ref"), child(at, "source_ref"), "provenance source_ref"),
            None if record.get("license") is None else _string(record.get("license"), child(at, "license"), "provenance license"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "created_at": self.created_at,
            "generator": self.generator,
            "prompt_sha256": self.prompt_sha256,
            "source_ref": self.source_ref,
            "license": self.license,
        }


@dataclass(frozen=True)
class AssetRecord:
    """An immutable, content-addressed asset with revisioned provenance."""

    asset_id: str
    label: str
    alt: str | None
    media_type: str
    size: int
    sha256: str
    storage_key: str
    provenance: AssetProvenance
    at: str

    @classmethod
    def parse(cls, value: Any, at: str) -> "AssetRecord":
        record = _object(value, at, "asset")
        _closed(record, {"id", "label", "alt", "media_type", "bytes", "sha256", "storage_key", "provenance"}, at, "asset")
        asset_id = _identifier(record.get("id"), child(at, "id"), "asset id")
        media_type = _string(record.get("media_type"), child(at, "media_type"), "asset media_type")
        if media_type not in ASSET_MEDIA_TYPES:
            fail("PRES_ASSET_MIME_MISMATCH", f"asset media_type {media_type!r} is not supported", child(at, "media_type"))
        digest = _digest(record.get("sha256"), child(at, "sha256"), "asset sha256")
        storage_key = _relative_key(record.get("storage_key"), child(at, "storage_key"), "asset storage_key")
        if storage_key != f"sha256/{digest}":
            fail(
                "PRES_ASSET_STORAGE_KEY_MISMATCH",
                "asset storage_key must be sha256/<declared digest>",
                child(at, "storage_key"),
            )
        alt = record.get("alt")
        if alt is not None:
            alt = _string(alt, child(at, "alt"), "asset alt")
        elif media_type.startswith("image/"):
            fail("PRES_ASSET_ALT_MISSING", "a visual asset requires alt text", at)
        return cls(
            asset_id,
            _string(record.get("label"), child(at, "label"), "asset label"),
            alt,
            media_type,
            _size(record.get("bytes"), child(at, "bytes"), "asset bytes", maximum=MAX_ASSET_BYTES),
            digest,
            storage_key,
            AssetProvenance.parse(record.get("provenance"), child(at, "provenance")),
            at,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.asset_id,
            "label": self.label,
            "alt": self.alt,
            "media_type": self.media_type,
            "bytes": self.size,
            "sha256": self.sha256,
            "storage_key": self.storage_key,
            "provenance": self.provenance.as_dict(),
        }


@dataclass(frozen=True)
class Transition:
    """One checkpoint's half of a navigable edge; animation need not invert."""

    edge_id: str | None
    forward_to: str | None
    back_edge_id: str | None
    back_to: str | None
    linear: bool
    forward: dict[str, Any]
    reverse: dict[str, Any]
    duration_ms: int | None
    export_boundary: bool
    timeout_ms: int | None = None

    @classmethod
    def parse(cls, value: Any, at: str) -> "Transition":
        if value is None:
            return cls(None, None, None, None, False, {}, {}, None, False)
        record = _object(value, at, "transition")
        _closed(
            record,
            {"edge_id", "forward_to", "back_edge_id", "back_to", "linear", "forward", "reverse", "duration_ms", "export_boundary", "timeout_ms"},
            at,
            "transition",
        )
        forward_to = record.get("forward_to")
        back_to = record.get("back_to")
        edge_id = record.get("edge_id")
        back_edge_id = record.get("back_edge_id")
        linear = _bool(record.get("linear"), child(at, "linear"), "transition linear")
        if forward_to is not None:
            forward_to = _identifier(forward_to, child(at, "forward_to"), "transition forward_to")
        if back_to is not None:
            back_to = _identifier(back_to, child(at, "back_to"), "transition back_to")
        if edge_id is not None:
            edge_id = _identifier(edge_id, child(at, "edge_id"), "transition edge_id")
        if back_edge_id is not None:
            back_edge_id = _identifier(back_edge_id, child(at, "back_edge_id"), "transition back_edge_id")
            if back_to is None:
                fail("PRES_FIELD_INVALID", "back_edge_id requires a back_to endpoint", child(at, "back_edge_id"))
        # A middle checkpoint ends one edge and starts another, so the reverse
        # half may carry its own id; the single-half form keeps edge_id.
        if back_to is not None and back_edge_id is None:
            back_edge_id = edge_id
        if forward_to is not None and edge_id is None:
            fail("PRES_EDGE_INCOMPLETE", "a forward transition requires an edge_id", at)
        if back_to is not None and back_edge_id is None:
            fail("PRES_EDGE_INCOMPLETE", "a reverse transition requires an edge_id", at)
        if forward_to is not None and back_to is not None and edge_id == back_edge_id:
            fail("PRES_EDGE_AMBIGUOUS", f"one checkpoint cannot declare both halves of edge {edge_id!r}", at)
        if linear and (forward_to is not None or back_to is not None):
            fail("PRES_EDGE_AMBIGUOUS", "a checkpoint cannot declare both a linear opt-in and an explicit endpoint", at)
        duration = record.get("duration_ms")
        if duration is not None:
            duration = _size(duration, child(at, "duration_ms"), "transition duration_ms", maximum=24 * 60 * 60 * 1000)
        timeout = record.get("timeout_ms")
        if timeout is not None:
            timeout = _size(timeout, child(at, "timeout_ms"), "transition timeout_ms", maximum=24 * 60 * 60 * 1000)
            if timeout == 0:
                fail("PRES_FIELD_INVALID", "transition timeout_ms must be positive", child(at, "timeout_ms"))
        return cls(
            edge_id,
            forward_to,
            back_edge_id,
            back_to,
            linear,
            _metadata(record.get("forward"), child(at, "forward"), "transition forward metadata"),
            _metadata(record.get("reverse"), child(at, "reverse"), "transition reverse metadata"),
            duration,
            _bool(record.get("export_boundary"), child(at, "export_boundary"), "transition export_boundary"),
            timeout,
        )


@dataclass(frozen=True)
class Claim:
    """One material assertion a state makes, and what the closure says about it.

    Ids only name records in the revision's pinned knowledge closure; resolving
    them is the validator's job. A claim marked anything but `unassessed` with
    nothing behind it is refused there, so authorship cannot mint support.
    """

    text: str
    target: str | None
    doxai: tuple[str, ...]
    evidence: tuple[str, ...]
    qualification: str | None
    status: str

    @classmethod
    def parse(cls, value: Any, at: str) -> "Claim":
        record = _object(value, at, "claim")
        _closed(record, {"text", "target", "doxai", "evidence", "qualification", "status"}, at, "claim")
        status = _string(record.get("status", "unassessed"), child(at, "status"), "claim status")
        if status not in CLAIM_STATUSES:
            fail("PRES_FIELD_INVALID", f"claim status {status!r} is not supported", child(at, "status"))
        references: dict[str, tuple[str, ...]] = {}
        for key, prefix in (("doxai", "d-"), ("evidence", "e-")):
            raw = record.get(key, [])
            if not isinstance(raw, list) or len(raw) > MAX_CLAIMS:
                fail("PRES_FIELD_INVALID", f"claim {key} must be a bounded array", child(at, key))
            items = tuple(_string(item, child(at, key, index), f"claim {key} reference") for index, item in enumerate(raw))
            for index, item in enumerate(items):
                if _KNOWLEDGE_ID.fullmatch(item) is None or not item.startswith(prefix):
                    fail("PRES_FIELD_INVALID", f"claim {key} reference {item!r} is not a {prefix}* identifier", child(at, key, index))
            _unique(items, child(at, key), "PRES_FIELD_INVALID", f"claim {key}")
            references[key] = items
        target = record.get("target")
        qualification = record.get("qualification")
        return cls(
            _string(record.get("text"), child(at, "text"), "claim text"),
            None if target is None else _string(target, child(at, "target"), "claim target"),
            references["doxai"],
            references["evidence"],
            None if qualification is None else _string(qualification, child(at, "qualification"), "claim qualification"),
            status,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "target": self.target,
            "doxai": list(self.doxai),
            "evidence": list(self.evidence),
            "qualification": self.qualification,
            "status": self.status,
        }


@dataclass(frozen=True)
class KnowledgeBinding:
    """Which argument a rendering serves, and where its pinned closure lives."""

    thesis: str | None
    diegesis: str | None
    walk: str | None
    closure: str | None

    @classmethod
    def parse(cls, value: Any, at: str) -> "KnowledgeBinding":
        if value is None:
            return cls(None, None, None, None)
        record = _object(value, at, "knowledge")
        _closed(record, {"thesis", "diegesis", "walk", "closure"}, at, "knowledge")
        diegesis = record.get("diegesis")
        if diegesis is not None:
            diegesis = _string(diegesis, child(at, "diegesis"), "knowledge diegesis")
            if _KNOWLEDGE_ID.fullmatch(diegesis) is None or not diegesis.startswith("n-"):
                fail("PRES_FIELD_INVALID", f"knowledge diegesis {diegesis!r} is not an n-* identifier", child(at, "diegesis"))
        walk = record.get("walk")
        if walk is not None:
            walk = _string(walk, child(at, "walk"), "knowledge walk")
            if diegesis is None:
                fail("PRES_FIELD_INVALID", "a knowledge walk requires a diegesis", child(at, "walk"))
        thesis = record.get("thesis")
        closure = record.get("closure")
        return cls(
            None if thesis is None else _identifier(thesis, child(at, "thesis"), "knowledge thesis"),
            diegesis,
            walk,
            None if closure is None else _relative_key(closure, child(at, "closure"), "knowledge closure"),
        )

    @property
    def declared(self) -> bool:
        return any((self.thesis, self.diegesis, self.walk, self.closure))

    def as_dict(self) -> dict[str, Any]:
        return {"thesis": self.thesis, "diegesis": self.diegesis, "walk": self.walk, "closure": self.closure}


@dataclass(frozen=True)
class Checkpoint:
    """A stable, registered, absolutely seekable state."""

    checkpoint_id: str
    label: str
    source: str
    entry: str
    document: str
    styles: str | None
    notes: str | None
    modules: tuple[str, ...]
    assets: tuple[str, ...]
    capabilities: tuple[str, ...]
    transition: Transition
    at: str
    scene: str | None = None
    claims: tuple[Claim, ...] = ()
    mode: str = "stage"
    cues: tuple[str, ...] = ()
    #: What the presenter says at each cue, authored per cue because a cue is
    #: the moment the next thing is said.
    cue_notes: tuple[tuple[str, str], ...] = ()

    @classmethod
    def parse(cls, value: Any, at: str) -> "Checkpoint":
        record = _object(value, at, "checkpoint")
        _closed(
            record,
            {"id", "label", "source", "entry", "document", "styles", "notes", "modules", "assets", "capabilities", "transition", "scene", "claims", "mode", "cues", "cue_notes"},
            at,
            "checkpoint",
        )
        source = _relative_key(record.get("source"), child(at, "source"), "checkpoint source")
        modules_raw = record.get("modules", [])
        if not isinstance(modules_raw, list) or len(modules_raw) > MAX_MODULES:
            fail("PRES_FIELD_INVALID", "checkpoint modules must be a bounded array", child(at, "modules"))
        modules = tuple(
            _relative_key(item, child(at, "modules", index), "checkpoint module") for index, item in enumerate(modules_raw)
        )
        _unique(modules, child(at, "modules"), "PRES_FIELD_INVALID", "checkpoint modules")
        assets_raw = record.get("assets", [])
        if not isinstance(assets_raw, list) or len(assets_raw) > MAX_ASSETS:
            fail("PRES_FIELD_INVALID", "checkpoint assets must be a bounded array", child(at, "assets"))
        assets = tuple(
            _identifier(item, child(at, "assets", index), "checkpoint asset reference") for index, item in enumerate(assets_raw)
        )
        _unique(assets, child(at, "assets"), "PRES_FIELD_INVALID", "checkpoint assets")
        capabilities_raw = record.get("capabilities", [])
        if not isinstance(capabilities_raw, list) or len(capabilities_raw) > len(CAPABILITIES):
            fail("PRES_CAPABILITY_INVALID", "checkpoint capabilities must be a bounded array", child(at, "capabilities"))
        capabilities: list[str] = []
        for index, item in enumerate(capabilities_raw):
            capability = _string(item, child(at, "capabilities", index), "checkpoint capability")
            if capability not in CAPABILITIES:
                fail(
                    "PRES_CAPABILITY_INVALID",
                    f"capability {capability!r} is outside the brokered vocabulary",
                    child(at, "capabilities", index),
                )
            capabilities.append(capability)
        _unique(tuple(capabilities), child(at, "capabilities"), "PRES_CAPABILITY_INVALID", "checkpoint capabilities")
        styles = record.get("styles")
        notes = record.get("notes")
        claims_raw = record.get("claims", [])
        if not isinstance(claims_raw, list) or len(claims_raw) > MAX_CLAIMS:
            fail("PRES_FIELD_INVALID", "checkpoint claims must be a bounded array", child(at, "claims"))
        claims = tuple(Claim.parse(item, child(at, "claims", index)) for index, item in enumerate(claims_raw))
        mode = record.get("mode", "stage")
        if mode not in CHECKPOINT_MODES:
            fail("PRES_FIELD_INVALID", f"checkpoint mode {mode!r} is not supported", child(at, "mode"))
        cues_raw = record.get("cues", [])
        if not isinstance(cues_raw, list) or len(cues_raw) > MAX_CUES:
            fail("PRES_FIELD_INVALID", "checkpoint cues must be a bounded array", child(at, "cues"))
        cues = tuple(
            _identifier(item, child(at, "cues", index), "checkpoint cue") for index, item in enumerate(cues_raw)
        )
        _unique(cues, child(at, "cues"), "PRES_FIELD_INVALID", "checkpoint cues")
        # A cue is a position the session can name, so it only means something
        # where the realm owns the geometry that selects it.
        if cues and mode != "document":
            fail("PRES_FIELD_INVALID", "only a document-mode checkpoint declares cues", child(at, "cues"))
        notes_raw = record.get("cue_notes") or {}
        if not isinstance(notes_raw, dict) or len(notes_raw) > MAX_CUES:
            fail("PRES_FIELD_INVALID", "checkpoint cue_notes must be a bounded object", child(at, "cue_notes"))
        # Sorted by cue: a mapping's authored order is not identity, and the
        # revision digest covers this tuple.
        cue_notes = tuple(
            sorted(
                (
                    (
                        _identifier(cue, child(at, "cue_notes", cue), "cue_notes cue"),
                        _relative_key(key, child(at, "cue_notes", cue), "cue_notes source"),
                    )
                    for cue, key in notes_raw.items()
                ),
                key=lambda pair: pair[0],
            )
        )
        for cue, _ in cue_notes:
            if cue not in cues:
                fail("PRES_FIELD_INVALID", f"cue_notes names {cue!r}, which this checkpoint does not declare", child(at, "cue_notes", cue))
        return cls(
            _identifier(record.get("id"), child(at, "id"), "checkpoint id"),
            _string(record.get("label"), child(at, "label"), "checkpoint label"),
            source,
            _relative_key(record.get("entry"), child(at, "entry"), "checkpoint entry"),
            _relative_key(record.get("document"), child(at, "document"), "checkpoint document"),
            None if styles is None else _relative_key(styles, child(at, "styles"), "checkpoint styles"),
            None if notes is None else _relative_key(notes, child(at, "notes"), "checkpoint notes"),
            modules,
            assets,
            tuple(capabilities),
            Transition.parse(record.get("transition"), child(at, "transition")),
            at,
            None if record.get("scene") is None else _identifier(record["scene"], child(at, "scene"), "checkpoint scene"),
            claims,
            mode,
            cues,
            cue_notes,
        )

    @property
    def files(self) -> tuple[tuple[str, str], ...]:
        """Every revisioned file of this checkpoint in declared order."""

        entries: list[tuple[str, str]] = [("entry", self.entry), ("document", self.document)]
        if self.styles is not None:
            entries.append(("styles", self.styles))
        if self.notes is not None:
            entries.append(("notes", self.notes))
        entries.extend((f"cue-notes:{cue}", key) for cue, key in self.cue_notes)
        entries.extend(("module", module) for module in self.modules)
        return tuple((role, f"{self.source}/{key}") for role, key in entries)


@dataclass(frozen=True)
class Group:
    """Optional slide/section grouping; never a cursor or navigation owner."""

    group_id: str
    kind: str
    label: str
    checkpoints: tuple[str, ...]
    export_boundary: bool
    at: str

    @classmethod
    def parse(cls, value: Any, at: str) -> "Group":
        record = _object(value, at, "group")
        _closed(record, {"id", "kind", "label", "checkpoints", "export_boundary"}, at, "group")
        kind = _string(record.get("kind"), child(at, "kind"), "group kind")
        if kind not in GROUP_KINDS:
            fail("PRES_FIELD_INVALID", f"group kind {kind!r} is not supported", child(at, "kind"))
        members_raw = record.get("checkpoints", [])
        if not isinstance(members_raw, list) or len(members_raw) > MAX_CHECKPOINTS:
            fail("PRES_FIELD_INVALID", "group checkpoints must be a bounded array", child(at, "checkpoints"))
        members = tuple(
            _identifier(item, child(at, "checkpoints", index), "group checkpoint") for index, item in enumerate(members_raw)
        )
        _unique(members, child(at, "checkpoints"), "PRES_GROUP_MEMBER_DUPLICATE", "group checkpoints")
        return cls(
            _identifier(record.get("id"), child(at, "id"), "group id"),
            kind,
            _string(record.get("label"), child(at, "label"), "group label"),
            members,
            _bool(record.get("export_boundary"), child(at, "export_boundary"), "group export_boundary"),
            at,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.group_id,
            "kind": self.kind,
            "label": self.label,
            "checkpoints": list(self.checkpoints),
            "export_boundary": self.export_boundary,
        }


@dataclass(frozen=True)
class StyleRecord:
    """A reusable prompt fragment, and the reference assets it contributes.

    Styles are authored deck content, not request parameters: a generation that
    names one has to resolve it against the revision it was submitted for, so
    the text a `prompt_sha256` attests to is a thing the deck stored rather than
    whatever a client happened to inline that afternoon.
    """

    style_id: str
    text: str
    references: tuple[str, ...]
    at: str

    @classmethod
    def parse(cls, value: Any, at: str) -> "StyleRecord":
        record = _object(value, at, "style")
        _closed(record, {"id", "text", "references"}, at, "style")
        references_raw = record.get("references", [])
        if not isinstance(references_raw, list) or len(references_raw) > MAX_ASSETS:
            fail("PRES_FIELD_INVALID", "style references must be a bounded array", child(at, "references"))
        references = tuple(
            _identifier(item, child(at, "references", index), "style reference")
            for index, item in enumerate(references_raw)
        )
        _unique(references, child(at, "references"), "PRES_STYLE_REFERENCE_DUPLICATE", "style references")
        return cls(
            _identifier(record.get("id"), child(at, "id"), "style id"),
            _string(record.get("text"), child(at, "text"), "style text"),
            references,
            at,
        )

    def as_dict(self) -> dict[str, object]:
        return {"id": self.style_id, "text": self.text, "references": list(self.references)}


@dataclass(frozen=True)
class Edge:
    """A registered two-way navigation edge with independently authored motion."""

    edge_id: str
    from_id: str
    to_id: str
    forward: dict[str, Any]
    reverse: dict[str, Any]
    duration_ms: int | None
    export_boundary: bool
    generated: bool
    timeout_ms: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.edge_id,
            "from": self.from_id,
            "to": self.to_id,
            "forward": self.forward,
            "reverse": self.reverse,
            "duration_ms": self.duration_ms,
            "export_boundary": self.export_boundary,
            "generated": self.generated,
            **({"timeout_ms": self.timeout_ms} if self.timeout_ms is not None else {}),
        }


@dataclass(frozen=True)
class PresentationManifest:
    """The parsed, closed v2 manifest plus its revision-bearing source."""

    presentation_id: str
    declared_revision: str | None
    checkpoint_order: tuple[str, ...]
    checkpoints: tuple[Checkpoint, ...]
    groups: tuple[Group, ...]
    assets: tuple[AssetRecord, ...]
    styles: tuple[StyleRecord, ...]
    source: dict[str, Any]
    knowledge: KnowledgeBinding = KnowledgeBinding(None, None, None, None)

    @classmethod
    def parse(cls, value: Any, log: DiagnosticLog) -> "PresentationManifest":
        record = _object(value, "", "manifest")
        _closed(record, {"schema", "presentation_id", "revision", "checkpoint_order", "checkpoints", "groups", "assets", "styles", "knowledge"}, "", "manifest")
        knowledge = KnowledgeBinding.parse(record.get("knowledge"), pointer("knowledge"))
        schema = record.get("schema")
        if schema != MANIFEST_SCHEMA:
            fail("PRES_SCHEMA_UNSUPPORTED", f"manifest schema must be {MANIFEST_SCHEMA!r}", pointer("schema"))
        presentation_id = _identifier(record.get("presentation_id"), pointer("presentation_id"), "presentation_id")
        declared_revision = record.get("revision")
        if declared_revision is not None:
            declared_revision = _string(declared_revision, pointer("revision"), "revision")
            if _REVISION.fullmatch(declared_revision) is None:
                fail("PRES_FIELD_INVALID", "revision must be sha256:<64 lowercase hex characters>", pointer("revision"))
        order_raw = record.get("checkpoint_order")
        if not isinstance(order_raw, list) or not order_raw or len(order_raw) > MAX_CHECKPOINTS:
            fail("PRES_FIELD_INVALID", "checkpoint_order must be a non-empty bounded array", pointer("checkpoint_order"))
        checkpoint_order = tuple(
            _identifier(item, pointer("checkpoint_order", index), "checkpoint_order entry") for index, item in enumerate(order_raw)
        )
        _unique(checkpoint_order, pointer("checkpoint_order"), "PRES_CHECKPOINT_ID_DUPLICATE", "checkpoint_order")
        checkpoints_raw = record.get("checkpoints")
        if not isinstance(checkpoints_raw, list) or not checkpoints_raw or len(checkpoints_raw) > MAX_CHECKPOINTS:
            fail("PRES_FIELD_INVALID", "checkpoints must be a non-empty bounded array", pointer("checkpoints"))
        groups_raw = record.get("groups", [])
        if not isinstance(groups_raw, list) or len(groups_raw) > MAX_GROUPS:
            fail("PRES_FIELD_INVALID", "groups must be a bounded array", pointer("groups"))
        assets_raw = record.get("assets", [])
        if not isinstance(assets_raw, list) or len(assets_raw) > MAX_ASSETS:
            fail("PRES_FIELD_INVALID", "assets must be a bounded array", pointer("assets"))
        styles_raw = record.get("styles", [])
        if not isinstance(styles_raw, list) or len(styles_raw) > MAX_STYLES:
            fail("PRES_FIELD_INVALID", "styles must be a bounded array", pointer("styles"))

        checkpoints: list[Checkpoint] = []
        for index, item in enumerate(checkpoints_raw):
            with log.capture():
                checkpoints.append(Checkpoint.parse(item, pointer("checkpoints", index)))
        groups: list[Group] = []
        for index, item in enumerate(groups_raw):
            with log.capture():
                groups.append(Group.parse(item, pointer("groups", index)))
        assets: list[AssetRecord] = []
        for index, item in enumerate(assets_raw):
            with log.capture():
                assets.append(AssetRecord.parse(item, pointer("assets", index)))
        styles: list[StyleRecord] = []
        for index, item in enumerate(styles_raw):
            with log.capture():
                styles.append(StyleRecord.parse(item, pointer("styles", index)))
        return cls(
            presentation_id,
            declared_revision,
            checkpoint_order,
            tuple(checkpoints),
            tuple(groups),
            tuple(assets),
            tuple(styles),
            record,
            knowledge,
        )

    @property
    def revision_input_source(self) -> dict[str, Any]:
        """Manifest source with the calculated top-level revision removed."""

        return {key: value for key, value in self.source.items() if key != "revision"}


def group_memberships(groups: Iterable[Group]) -> dict[str, tuple[str, ...]]:
    """Map each checkpoint id to its groups; membership is optional metadata."""

    memberships: dict[str, list[str]] = {}
    for group in groups:
        for checkpoint_id in group.checkpoints:
            memberships.setdefault(checkpoint_id, []).append(group.group_id)
    return {key: tuple(value) for key, value in memberships.items()}


def build_edges(order: Sequence[str], checkpoints: Mapping[str, Checkpoint], log: DiagnosticLog) -> tuple[Edge, ...]:
    """Pair declared transition halves into registered, reversible edges.

    An edge exists only when both endpoints and both halves are registered in
    this revision. The linear edge is generated solely for adjacent ordered
    checkpoints that both opt in, and it stays a checkpoint-to-checkpoint edge.
    """

    forwards: dict[str, tuple[Checkpoint, str]] = {}
    reverses: dict[str, tuple[Checkpoint, str]] = {}
    for checkpoint_id in order:
        checkpoint = checkpoints[checkpoint_id]
        transition = checkpoint.transition
        at = child(checkpoint.at, "transition")
        for endpoint, half, half_id, table in (
            (transition.forward_to, "forward_to", transition.edge_id, forwards),
            (transition.back_to, "back_to", transition.back_edge_id, reverses),
        ):
            if endpoint is None or half_id is None:
                continue
            if endpoint not in checkpoints:
                log.fail(
                    "PRES_CHECKPOINT_UNKNOWN",
                    f"transition {half} names checkpoint {endpoint!r}, which is not in this revision",
                    child(at, half),
                )
                continue
            if half_id in table:
                log.fail(
                    "PRES_EDGE_ID_DUPLICATE",
                    f"edge {half_id!r} already declares a {half} half",
                    child(at, "edge_id"),
                )
                continue
            table[half_id] = (checkpoint, endpoint)

    edges: list[Edge] = []
    emitted: set[str] = set()
    for index, checkpoint_id in enumerate(order):
        checkpoint = checkpoints[checkpoint_id]
        transition = checkpoint.transition
        at = child(checkpoint.at, "transition")
        edge_id = transition.edge_id
        if edge_id is not None and transition.forward_to is not None and forwards.get(edge_id, (None, None))[0] is checkpoint:
            reverse = reverses.get(edge_id)
            target = forwards[edge_id][1]
            if reverse is None:
                log.fail(
                    "PRES_EDGE_INCOMPLETE",
                    f"edge {edge_id!r} declares no reverse half; a forward edge must be reversible",
                    child(at, "edge_id"),
                )
                continue
            reverse_checkpoint, back_to = reverse
            if reverse_checkpoint.checkpoint_id != target or back_to != checkpoint_id:
                log.fail(
                    "PRES_EDGE_ENDPOINT_MISMATCH",
                    f"edge {edge_id!r} reverse half returns to {back_to!r} from {reverse_checkpoint.checkpoint_id!r}",
                    child(reverse_checkpoint.at, "transition", "back_to"),
                )
                continue
            edges.append(
                Edge(
                    edge_id,
                    checkpoint_id,
                    target,
                    transition.forward,
                    reverse_checkpoint.transition.reverse,
                    transition.duration_ms if transition.duration_ms is not None else reverse_checkpoint.transition.duration_ms,
                    transition.export_boundary or reverse_checkpoint.transition.export_boundary,
                    False,
                    transition.timeout_ms if transition.timeout_ms is not None else reverse_checkpoint.transition.timeout_ms,
                )
            )
            emitted.add(edge_id)
            continue
        successor = order[index + 1] if index + 1 < len(order) else None
        if transition.linear and successor is not None and checkpoints[successor].transition.linear:
            generated_id = f"linear:{checkpoint_id}->{successor}"
            if generated_id in emitted:
                log.fail("PRES_EDGE_ID_DUPLICATE", f"edge {generated_id!r} is declared twice", at)
                continue
            edges.append(Edge(
                generated_id, checkpoint_id, successor, transition.forward, checkpoints[successor].transition.reverse,
                transition.duration_ms, transition.export_boundary, True, transition.timeout_ms,
            ))
            emitted.add(generated_id)

    for edge_id, (checkpoint, _) in sorted(reverses.items()):
        if edge_id not in forwards:
            log.fail(
                "PRES_EDGE_INCOMPLETE",
                f"edge {edge_id!r} declares no forward half",
                child(checkpoint.at, "transition", "edge_id"),
            )
    return tuple(edges)


def asset_closure_digest(assets: Iterable[AssetRecord]) -> str:
    """Digest of every declared asset record sorted by asset id."""

    ordered = [asset.as_dict() for asset in sorted(assets, key=lambda item: item.asset_id)]
    return sha256(b"doxagon-presentation-asset-closure/v2\0" + canonical_json(ordered))
