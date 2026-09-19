"""Static parsing of checkpoint registrations — author code is never executed.

The validator reads the registration block, the module byte digest, the
declared id/version, the asset closure, and the allowed capabilities purely by
inspecting bytes. Nothing in this module evaluates, imports, transpiles, or
subprocesses author-supplied HTML, CSS, or JavaScript; the sandbox realm is the
only place a checkpoint program ever runs.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Callable, Iterable, TypeVar

from doxagon.html_editions.contracts import sha256

from .contracts import (
    CAPABILITIES,
    REGISTRATION_SCHEMA,
    _duplicate_free,
    _identifier,
    _object,
    _string,
    child,
    pointer,
)
from .errors import Diagnostic, PresentationError, fail
from .javascript import SCAN_POLICY, code_projection, module_specifiers

_T = TypeVar("_T")

REGISTRATION_MARKER = "doxagon-checkpoint-registration"
_REGISTRATION_BLOCK = re.compile(
    r"/\*\s*" + re.escape(REGISTRATION_MARKER) + r"\s*\n(?P<body>.*?)\n\s*\*/",
    re.DOTALL,
)
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,31}\Z")

# Executable escapes from the pinned-bytes model. Every one of these can turn a
# digest-pinned module into code the revision never saw. Every pattern below
# runs over the code projection, where optional chaining is canonicalized to
# plain member and call punctuation, so `eval?.(x)` and `eval(x)` — and
# `document?.write?.(x)` and `document.write(x)` — match the same rule.
_UNSAFE_JS = (
    (re.compile(r"\beval\s*\("), "eval() is not permitted in a checkpoint module"),
    # One call pattern: the projection blanks the argument literal a
    # quote-anchored pattern used to need, and `new` is optional at the call.
    (re.compile(r"(?<![$\w])Function\s*\("), "the Function constructor is not permitted in a checkpoint module"),
    (re.compile(r"(?<![.\w$])import\s*\("), "dynamic import() is not permitted in a checkpoint module"),
    (re.compile(r"\bimportScripts\s*\("), "importScripts() is not permitted in a checkpoint module"),
    (re.compile(r"\bdocument\s*\.\s*write\s*\("), "document.write() is not permitted in a checkpoint module"),
    (re.compile(r"\bsrcdoc\b"), "srcdoc injection is not permitted in a checkpoint module"),
)
_REMOTE_REFERENCE = re.compile(r"https?://|wss?://|javascript:|data:text/html|blob:", re.IGNORECASE)

# Host APIs a checkpoint may only touch through an explicitly granted, brokered
# capability. A token found without its grant is a validation failure, not a
# runtime surprise.
_CAPABILITY_TOKENS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("network", re.compile(r"\bfetch\s*\(|\bXMLHttpRequest\b|\bEventSource\b|\bnew\s+WebSocket\b|\bsendBeacon\s*\(")),
    ("timers", re.compile(r"\bsetTimeout\s*\(|\bsetInterval\s*\(|\brequestAnimationFrame\s*\(|\bqueueMicrotask\s*\(")),
    ("storage", re.compile(r"\blocalStorage\b|\bsessionStorage\b|\bindexedDB\b|\bcaches\b|\bdocument\s*\.\s*cookie\b")),
    ("media", re.compile(r"\bmediaDevices\b|\bgetUserMedia\s*\(|\bnew\s+Audio\s*\(|\bcaptureStream\s*\(")),
    ("clipboard", re.compile(r"\bnavigator\s*\.\s*clipboard\b|\bexecCommand\s*\(")),
    ("worker", re.compile(r"\bnew\s+Worker\s*\(|\bnew\s+SharedWorker\s*\(|\bserviceWorker\b")),
    ("export", re.compile(r"\bwindow\s*\.\s*print\s*\(|\bshowSaveFilePicker\s*\(")),
)

# Arbitrary DOM stays legal — canvas, SVG, WebGL, video elements, and any
# structure an author wants. Only host escapes and unpinned code are refused.
_UNSAFE_HTML = (
    # Both ends of the element: a lone closer opens no script here, but it does
    # close whichever one carries this document downstream.
    (re.compile(r"<\s*/?\s*script\b", re.IGNORECASE), "checkpoint documents carry no inline script; register a module instead"),
    (re.compile(r"<\s*(?:base|iframe|frame|frameset|object|embed|portal)\b", re.IGNORECASE), "checkpoint documents cannot embed a foreign browsing context"),
    (re.compile(r"\son[a-z]+\s*=", re.IGNORECASE), "checkpoint documents cannot carry inline event handlers"),
    (re.compile(r"https?://|javascript:|data:text/html|blob:", re.IGNORECASE), "checkpoint documents cannot reference remote or executable URLs"),
    (re.compile(r"(?:src|href)\s*=\s*[\"']//", re.IGNORECASE), "checkpoint documents cannot reference protocol-relative URLs"),
)
_UNSAFE_CSS = (
    (re.compile(r"@\s*import\b", re.IGNORECASE), "checkpoint styles cannot import another stylesheet"),
    (re.compile(r"url\s*\(\s*[\"']?\s*(?:https?:|//|file:|blob:|javascript:)", re.IGNORECASE), "checkpoint styles cannot reference a remote or executable URL"),
    (re.compile(r"\bexpression\s*\(|\bbehavior\s*:", re.IGNORECASE), "checkpoint styles cannot declare executable behaviour"),
)


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _field(parser: Callable[[Any, str, str], _T], value: Any, at: str, subject: str, path: str, line: int) -> _T:
    """Parse one registration scalar so its diagnostic always carries a source location."""

    try:
        return parser(value, at, subject)
    except PresentationError as error:
        found = error.diagnostic
        fail(found.code, found.message, found.pointer or at, found.path or path, found.line or line)


def _decode(raw: bytes, path: str, code: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        fail(code, "source is not UTF-8", "", path)


@dataclass(frozen=True)
class CheckpointRegistration:
    """Registration metadata parsed from module bytes without executing them."""

    checkpoint_id: str
    version: str
    module_sha256: str
    assets: tuple[str, ...]
    capabilities: tuple[str, ...]
    forward_to: str | None
    back_to: str | None
    description: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": REGISTRATION_SCHEMA,
            "id": self.checkpoint_id,
            "version": self.version,
            "module_sha256": self.module_sha256,
            "assets": list(self.assets),
            "capabilities": list(self.capabilities),
            "forward_to": self.forward_to,
            "back_to": self.back_to,
            "description": self.description,
        }


def parse_registration(raw: bytes, path: str) -> CheckpointRegistration:
    """Extract the single registration block from one checkpoint module."""

    text = _decode(raw, path, "PRES_REGISTRATION_INVALID")
    matches = list(_REGISTRATION_BLOCK.finditer(text))
    if not matches:
        fail("PRES_REGISTRATION_MISSING", f"module has no {REGISTRATION_MARKER} block", "", path, 1)
    if len(matches) > 1:
        fail(
            "PRES_REGISTRATION_INVALID",
            f"module declares {len(matches)} {REGISTRATION_MARKER} blocks; exactly one is allowed",
            "",
            path,
            _line_of(text, matches[1].start()),
        )
    match = matches[0]
    line = _line_of(text, match.start("body"))
    try:
        parsed = json.loads(match.group("body"), object_pairs_hook=_duplicate_free)
    except json.JSONDecodeError as error:
        fail("PRES_REGISTRATION_INVALID", f"registration block is not valid JSON: {error.msg}", "", path, line)
    except PresentationError as error:
        fail(error.diagnostic.code, error.diagnostic.message, "", path, line)
    record = _field(_object, parsed, "", "registration", path, line)
    unknown = sorted(set(record) - {"schema", "id", "version", "assets", "capabilities", "forward_to", "back_to", "description"})
    if unknown:
        fail("PRES_REGISTRATION_INVALID", f"registration declares unknown field {unknown[0]!r}", "", path, line)
    if record.get("schema") != REGISTRATION_SCHEMA:
        fail(
            "PRES_REGISTRATION_SCHEMA_UNSUPPORTED",
            f"registration schema must be {REGISTRATION_SCHEMA!r}",
            "",
            path,
            line,
        )
    version = _field(_string, record.get("version"), pointer("version"), "registration version", path, line)
    if _VERSION.fullmatch(version) is None:
        fail("PRES_REGISTRATION_INVALID", "registration version is not a supported version string", pointer("version"), path, line)
    assets_raw = record.get("assets", [])
    capabilities_raw = record.get("capabilities", [])
    if not isinstance(assets_raw, list) or not isinstance(capabilities_raw, list):
        fail("PRES_REGISTRATION_INVALID", "registration assets and capabilities must be arrays", "", path, line)
    capabilities: list[str] = []
    for index, item in enumerate(capabilities_raw):
        at = pointer("capabilities", index)
        capability = _field(_string, item, at, "registration capability", path, line)
        if capability not in CAPABILITIES:
            fail(
                "PRES_CAPABILITY_INVALID",
                f"capability {capability!r} is outside the brokered vocabulary",
                at,
                path,
                line,
            )
        capabilities.append(capability)
    forward_to = record.get("forward_to")
    back_to = record.get("back_to")
    description = record.get("description")
    return CheckpointRegistration(
        _field(_identifier, record.get("id"), pointer("id"), "registration id", path, line),
        version,
        sha256(raw),
        tuple(
            _field(_identifier, item, pointer("assets", index), "registration asset", path, line)
            for index, item in enumerate(assets_raw)
        ),
        tuple(capabilities),
        None
        if forward_to is None
        else _field(_identifier, forward_to, pointer("forward_to"), "registration forward_to", path, line),
        None if back_to is None else _field(_identifier, back_to, pointer("back_to"), "registration back_to", path, line),
        None
        if description is None
        else _field(_string, description, pointer("description"), "registration description", path, line),
    )


def _resolve_specifier(specifier: str, importing_path: str) -> str | None:
    """Resolve a relative specifier against the directory of the importing file.

    Only a relative specifier can name bytes this revision pinned; a bare,
    absolute, or URL specifier resolves to nothing and is refused. A specifier
    that climbs above the presentation root also resolves to nothing.
    """

    if not specifier.startswith(("./", "../")):
        return None
    parts = importing_path.split("/")[:-1]
    for segment in specifier.split("/"):
        if segment in {"", "."}:
            continue
        if segment == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(segment)
    return "/".join(parts)


def scan_module(raw: bytes, path: str, registered_modules: Iterable[str]) -> tuple[Diagnostic, ...]:
    """Report unpinned code, remote references, and unregistered imports.

    ``path`` and every entry of ``registered_modules`` are keys relative to the
    presentation root, so each relative import specifier is resolved against the
    importing file's own directory before it is compared with the pinned set.
    Containment patterns run over the code projection, so a keyword inside a
    string or comment is text, not an executable escape; a remote reference is
    matched in the raw source because a URL is carried as a string literal.
    """

    text = _decode(raw, path, "PRES_REGISTRATION_INVALID")
    code = code_projection(text)
    found: list[Diagnostic] = []
    for expression, message in _UNSAFE_JS:
        match = expression.search(code)
        if match is not None:
            found.append(Diagnostic("PRES_REGISTRATION_UNSAFE_CODE", message, "", path, _line_of(text, match.start())))
    remote = _REMOTE_REFERENCE.search(text)
    if remote is not None:
        found.append(
            Diagnostic(
                "PRES_REGISTRATION_REMOTE_REFERENCE",
                "checkpoint modules cannot reference a remote or executable URL",
                "",
                path,
                _line_of(text, remote.start()),
            )
        )
    allowed = set(registered_modules)
    for index, specifier in module_specifiers(text):
        resolved = None if specifier is None else _resolve_specifier(specifier, path)
        if resolved is not None and resolved in allowed:
            continue
        message = (
            "import statement declares no static module specifier the validator can pin"
            if specifier is None
            else f"import specifier {specifier!r} is not a registered checkpoint module"
        )
        found.append(Diagnostic("PRES_REGISTRATION_UNREGISTERED_MODULE", message, "", path, _line_of(text, index)))
    return tuple(found)


def scan_capabilities(raw: bytes, path: str, granted: Iterable[str], at: str) -> tuple[Diagnostic, ...]:
    """Report each brokered host API the module touches without a grant."""

    text = _decode(raw, path, "PRES_REGISTRATION_INVALID")
    code = code_projection(text)
    allowed = set(granted)
    found: list[Diagnostic] = []
    for capability, expression in _CAPABILITY_TOKENS:
        if capability in allowed:
            continue
        match = expression.search(code)
        if match is not None:
            found.append(
                Diagnostic(
                    "PRES_CAPABILITY_UNGRANTED",
                    f"module uses the {capability!r} capability without a declared grant",
                    at,
                    path,
                    _line_of(text, match.start()),
                )
            )
    return tuple(found)


def scan_document(raw: bytes, path: str) -> tuple[Diagnostic, ...]:
    return _scan(raw, path, _UNSAFE_HTML, "PRES_DOCUMENT_UNSAFE")


def scan_styles(raw: bytes, path: str) -> tuple[Diagnostic, ...]:
    return _scan(raw, path, _UNSAFE_CSS, "PRES_STYLES_UNSAFE")


def _scan(raw: bytes, path: str, rules: Iterable[tuple[re.Pattern[str], str]], code: str) -> tuple[Diagnostic, ...]:
    text = _decode(raw, path, code)
    found: list[Diagnostic] = []
    for expression, message in rules:
        match = expression.search(text)
        if match is not None:
            found.append(Diagnostic(code, message, "", path, _line_of(text, match.start())))
    return tuple(found)


def registration_agreement(
    registration: CheckpointRegistration,
    checkpoint_id: str,
    declared_assets: Iterable[str],
    declared_capabilities: Iterable[str],
    forward_to: str | None,
    back_to: str | None,
    at: str,
    path: str,
) -> tuple[Diagnostic, ...]:
    """Compare the parsed registration with its manifest declaration."""

    found: list[Diagnostic] = []
    if registration.checkpoint_id != checkpoint_id:
        found.append(
            Diagnostic(
                "PRES_REGISTRATION_ID_MISMATCH",
                f"registration declares id {registration.checkpoint_id!r} for checkpoint {checkpoint_id!r}",
                child(at, "id"),
                path,
            )
        )
    assets = set(declared_assets)
    for asset_id in registration.assets:
        if asset_id not in assets:
            found.append(
                Diagnostic(
                    "PRES_REGISTRATION_ASSET_UNDECLARED",
                    f"registration claims asset {asset_id!r} outside the checkpoint asset closure",
                    child(at, "assets"),
                    path,
                )
            )
    capabilities = set(declared_capabilities)
    for capability in registration.capabilities:
        if capability not in capabilities:
            found.append(
                Diagnostic(
                    "PRES_CAPABILITY_UNGRANTED",
                    f"registration requests capability {capability!r} that the manifest does not grant",
                    child(at, "capabilities"),
                    path,
                )
            )
    for label, declared, manifest_value in (
        ("forward_to", registration.forward_to, forward_to),
        ("back_to", registration.back_to, back_to),
    ):
        # Exact equality in both directions: an omitted registration endpoint is
        # a claim of no edge, which a manifest endpoint contradicts.
        if declared != manifest_value:
            found.append(
                Diagnostic(
                    "PRES_REGISTRATION_EDGE_MISMATCH",
                    f"registration {label} {declared!r} does not match the manifest transition {manifest_value!r}",
                    child(at, "transition", label),
                    path,
                )
            )
    return tuple(found)


def policy_tokens() -> tuple[str, ...]:
    """Every static containment rule, so a receipt pins the policy that ran."""

    return tuple(
        sorted(
            [expression.pattern for expression, _ in _UNSAFE_JS]
            + [expression.pattern for expression, _ in _UNSAFE_HTML]
            + [expression.pattern for expression, _ in _UNSAFE_CSS]
            + [_REMOTE_REFERENCE.pattern, SCAN_POLICY]
            + [f"{capability}\t{expression.pattern}" for capability, expression in _CAPABILITY_TOKENS]
        )
    )
