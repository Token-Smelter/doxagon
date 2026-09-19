"""The one runtime: pinned bytes, deck payloads, and the sandbox host shell.

Preview, presenter, audience, agent capture, raster export, and the offline
export all load ``resources/runtime.js``. This module is the only place that
reads those bytes, pins their digest, and composes the payload they run, so a
second runtime cannot appear without deleting this one.

A payload carries the registered bytes of one validated revision — never a path,
a storage key, or a workspace-local reference — and it is built from the
promoted receipt, so an unvalidated tree can never be presented or exported.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from doxagon.html_editions.contracts import canonical_json, sha256

from .contracts import ASSET_ROOT, MANIFEST_KEY, RUNTIME_VERSION
from .errors import WorkspaceError
from .javascript import module_specifiers
from .sources import read_contained

DECK_SCHEMA = "doxagon.presentation-deck/2"

_RESOURCES = Path(__file__).parent / "resources"
RUNTIME_KEY = "runtime.js"
SHELL_KEY = "offline-shell.js"
SCROLL_SHELL_KEY = "scroll-shell.js"
DOCUMENT_SHELL_KEY = "document-shell.js"

# Capabilities a closed offline document can honour, a subset of the grant
# vocabulary (`contracts.CAPABILITIES`, itself the realm broker's own set).
# `worker` needs a resolvable worker origin a closed single-file document does
# not have, so an export that would need one fails closed instead of shipping a
# checkpoint that silently misbehaves offline.
OFFLINE_CAPABILITIES = frozenset({"timers", "media"})


def _resource(key: str) -> bytes:
    return (_RESOURCES / key).read_bytes()


def runtime_source() -> bytes:
    """The exact runtime bytes every surface loads."""

    return _resource(RUNTIME_KEY)


RUNTIME_SHA256 = sha256(runtime_source())


@dataclass(frozen=True)
class DeckPayload:
    """One validated revision rendered as digest-pinned runtime input."""

    revision: str
    payload: dict[str, Any]

    @property
    def digest(self) -> str:
        return sha256(b"doxagon-presentation-deck/v2\0" + canonical_json(self.payload))

    def as_dict(self) -> dict[str, Any]:
        return dict(self.payload)


def build_deck_payload(store: Any, revision: str | None = None) -> DeckPayload:
    """Read one promoted revision into the payload the runtime executes.

    Sources and asset bytes come from the revision tree through the contained
    reader, and the registered shape comes from the promoted receipt: a
    checkpoint the receipt does not carry cannot be presented.
    """

    target = revision or store.revision
    root = store.revision_root(target)
    manifest = store.read_manifest(target)
    receipt = store.read_receipt(target)
    if receipt.get("revision") != target:
        raise WorkspaceError("PRES_RECEIPT_STALE", "receipt does not describe this revision", status=409)
    verify_runtime_pin(receipt)

    assets = {str(record["id"]): record for record in manifest.get("assets", ())}
    registered = {str(item["id"]): item for item in receipt.get("checkpoints", ())}
    declared = {str(item["id"]): item for item in manifest.get("checkpoints", ())}

    checkpoints: list[dict[str, Any]] = []
    for checkpoint_id in receipt.get("checkpoint_order", ()):
        record = registered[str(checkpoint_id)]
        source = declared[str(checkpoint_id)]
        files = {str(item["role"]): str(item["path"]) for item in record.get("sources", ())}
        entry = _text(root, files["entry"])
        modules = [
            {
                "path": str(module),
                "source": _text(root, f"{source['source']}/{module}"),
            }
            for module in source.get("modules", ())
        ]
        if module_specifiers(entry) or any(module_specifiers(module["source"]) for module in modules):
            raise WorkspaceError(
                "PRES_RUNTIME_MODULE_GRAPH_UNSUPPORTED",
                f"checkpoint {checkpoint_id!r} imports a module graph this runtime cannot resolve",
                status=422,
            )
        checkpoints.append(
            {
                "id": str(checkpoint_id),
                "label": record["label"],
                "groups": list(record.get("groups", ())),
                **({"scene": record["scene"]} if "scene" in record else {}),
                **({"mode": record["mode"]} if "mode" in record else {}),
                **({"cues": list(record["cues"])} if "cues" in record else {}),
                "capabilities": list(record.get("capabilities", ())),
                "modules": modules,
                "registration": record.get("registration"),
                "entry": entry,
                "document": _text(root, files["document"]),
                "styles": _text(root, files["styles"]) if "styles" in files else "",
                "notes": _text(root, files["notes"]) if "notes" in files else None,
                **(
                    {
                        "cue_notes": {
                            role.split(":", 1)[1]: _text(root, path)
                            for role, path in files.items()
                            if role.startswith("cue-notes:")
                        }
                    }
                    if any(role.startswith("cue-notes:") for role in files)
                    else {}
                ),
                "assets": [_asset(root, assets[asset_id]) for asset_id in record.get("assets", ())],
            }
        )

    payload = {
        "schema": DECK_SCHEMA,
        "presentation_id": receipt["presentation_id"],
        "revision": target,
        "runtime_version": RUNTIME_VERSION,
        "runtime_sha256": RUNTIME_SHA256,
        "compose_hash": receipt["compose_hash"],
        "asset_closure_digest": receipt["asset_closure_digest"],
        "capability_grants": dict(receipt.get("capability_grants", {})),
        "export_policy": dict(receipt.get("export_policy", {})),
        "checkpoint_order": [str(item) for item in receipt.get("checkpoint_order", ())],
        "checkpoints": checkpoints,
        "edges": [dict(edge) for edge in receipt.get("edges", ())],
        "groups": [dict(group) for group in receipt.get("groups", ())],
    }
    return DeckPayload(target, payload)


def verify_runtime_pin(receipt: Mapping[str, Any]) -> None:
    """Refuse to run a revision under runtime bytes it never pinned.

    The receipt records the exact digest of the runtime that validated the
    revision (``receipt.RUNTIME_PIN``). Loading a revision under different bytes
    would change what an unchanged revision does, so it is refused here rather
    than silently presented: the deck must be revalidated, which recomputes a
    new revision over the new digest.
    """

    pinned = receipt.get("runtime")
    if not isinstance(pinned, Mapping) or pinned.get("sha256") != RUNTIME_SHA256 or pinned.get("version") != RUNTIME_VERSION:
        raise WorkspaceError(
            "PRES_RUNTIME_BYTES_MISMATCH",
            "this revision was validated against different runtime bytes; revalidate it before presenting or exporting",
            status=409,
        )


def _text(root: Path, key: str) -> str:
    data = read_contained(root, key)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise WorkspaceError("PRES_SOURCE_UNREADABLE", f"{key} is not UTF-8", status=422) from error


def _asset(root: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    data = read_contained(
        root, f"{ASSET_ROOT}/{record['storage_key']}", declared_size=int(record["bytes"]), maximum=64 * 1024 * 1024
    )
    if sha256(data) != record["sha256"]:
        raise WorkspaceError("PRES_ASSET_HASH_MISMATCH", f"asset {record['id']} does not match its digest", status=409)
    return {
        "id": record["id"],
        "label": record["label"],
        "alt": record["alt"],
        "media_type": record["media_type"],
        "base64": base64.b64encode(data).decode("ascii"),
    }


def unsupported_capabilities(payload: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Every (checkpoint, capability) an offline document cannot honour."""

    found: list[tuple[str, str]] = []
    for checkpoint in payload.get("checkpoints", ()):
        for capability in checkpoint.get("capabilities", ()):
            if capability not in OFFLINE_CAPABILITIES:
                found.append((str(checkpoint["id"]), str(capability)))
    return tuple(sorted(found))


_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}


def escape(value: str) -> str:
    return "".join(_ESCAPES.get(character, character) for character in value)


#: JSON is not HTML: a `</script>` inside any string the deck carries — a
#: speaker note, a label, a checkpoint document — would close the block it is
#: embedded in and hand the rest of the deck to the parser as markup. These five
#: characters are escaped to their JSON `\uXXXX` forms, which `JSON.parse`
#: restores exactly, so the embedded text survives byte for byte while no author
#: byte can terminate the element that carries it.
_JSON_IN_HTML = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", "\u2028": "\\u2028", "\u2029": "\\u2029"}


def embed_json(payload: Mapping[str, Any]) -> str:
    """Serialize a payload for embedding inside an HTML `<script>` element."""

    document = canonical_json(dict(payload)).decode("utf-8")
    return "".join(_JSON_IN_HTML.get(character, character) for character in document)


def unsupported_module_graphs(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Checkpoints that require unresolved imports rather than pinned sidecars."""

    found: list[str] = []
    for checkpoint in payload.get("checkpoints", ()):
        sources = [checkpoint.get("entry", "")]
        modules = checkpoint.get("modules", ())
        if not isinstance(modules, list):
            found.append(str(checkpoint["id"]))
            continue
        for module in modules:
            if not isinstance(module, Mapping) or not isinstance(module.get("source"), str):
                found.append(str(checkpoint["id"]))
                break
            sources.append(module["source"])
        else:
            if any(not isinstance(source, str) or module_specifiers(source) for source in sources):
                found.append(str(checkpoint["id"]))
    return tuple(sorted(set(found)))


def compose_offline_html(payload: Mapping[str, Any], *, title: str | None = None) -> bytes:
    """Compose one closed, self-contained document over the pinned runtime.

    The shell is the only privileged executable, its bytes are pinned by a CSP
    hash, and the document declares no network source at all: a load of this
    file issues zero ambient requests.
    """

    unsupported = unsupported_capabilities(payload)
    if unsupported:
        raise WorkspaceError(
            "PRES_EXPORT_CAPABILITY_UNSUPPORTED",
            f"checkpoint {unsupported[0][0]!r} requires capability {unsupported[0][1]!r}, which no closed document can honour",
            status=422,
        )
    module_graphs = unsupported_module_graphs(payload)
    if module_graphs:
        raise WorkspaceError(
            "PRES_RUNTIME_MODULE_GRAPH_UNSUPPORTED",
            f"checkpoint {module_graphs[0]!r} imports a module graph this runtime cannot resolve",
            status=422,
        )

    program = runtime_source().decode("utf-8") + "\n" + _resource(SHELL_KEY).decode("utf-8")
    # The deck is a JSON script block rather than a JS literal, and every byte
    # that could close that block early is escaped, so no author byte is ever
    # parsed as program text or markup by the shell.
    deck_json = embed_json(payload)
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{escape(_shell_csp(program))}">
<title>{escape(title or str(payload.get('presentation_id', 'presentation')))}</title>
<meta name="doxagon-revision" content="{escape(str(payload.get('revision', '')))}">
<meta name="doxagon-runtime" content="{escape(RUNTIME_VERSION)}">
<meta name="doxagon-runtime-sha256" content="{escape(RUNTIME_SHA256)}">
<style>{_SHELL_CSS}</style>
</head><body>
<main id="doxagon-deck" data-revision="{escape(str(payload.get('revision', '')))}">
<div id="doxagon-stage" aria-live="polite"></div>
<nav id="doxagon-controls" aria-label="Checkpoint controls"></nav>
</main>
<script type="application/json" id="doxagon-deck-payload">{deck_json}</script>
<script type="module">{program}</script>
</body></html>
"""
    return document.encode("utf-8")


def document_checkpoints(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Every checkpoint whose realm is the whole page rather than a stage."""

    return tuple(
        str(item["id"]) for item in payload.get("checkpoints", ()) if item.get("mode") == "document"
    )


def compose_document_html(payload: Mapping[str, Any], *, title: str | None = None) -> bytes:
    """One closed page whose realm owns the viewport, the scroll, and the layout.

    The host contributes no columns, no headings, and no scaffold: an authored
    document is the page. Callers pass the public projection, so no note travels.
    """

    unsupported = unsupported_capabilities(payload)
    if unsupported:
        raise WorkspaceError(
            "PRES_EXPORT_CAPABILITY_UNSUPPORTED",
            f"checkpoint {unsupported[0][0]!r} requires capability {unsupported[0][1]!r}, which no closed document can honour",
            status=422,
        )
    if not document_checkpoints(payload):
        raise WorkspaceError(
            "PRES_DOCUMENT_MODE_ABSENT",
            "this revision declares no document-mode checkpoint; export it as a deck or an article instead",
            status=422,
        )
    if any(checkpoint.get("notes") for checkpoint in payload.get("checkpoints", ())):
        raise WorkspaceError("PRES_PUBLIC_LEAK", "a published document is public; compose it from the projection", status=422)
    program = runtime_source().decode("utf-8") + "\n" + _resource(DOCUMENT_SHELL_KEY).decode("utf-8")
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{escape(_shell_csp(program))}">
<title>{escape(title or str(payload.get('presentation_id', 'document')))}</title>
<meta name="doxagon-revision" content="{escape(str(payload.get('revision', '')))}">
<meta name="doxagon-runtime" content="{escape(RUNTIME_VERSION)}">
<meta name="doxagon-runtime-sha256" content="{escape(RUNTIME_SHA256)}">
<style>{_DOCUMENT_CSS}</style>
</head><body>
<main id="doxagon-stage" data-revision="{escape(str(payload.get('revision', '')))}"></main>
<p id="doxagon-status" role="status"></p>
<script type="application/json" id="doxagon-deck-payload">{embed_json(payload)}</script>
<script type="module">{program}</script>
</body></html>
"""
    return document.encode("utf-8")


def compose_scroll_html(payload: Mapping[str, Any], *, title: str | None = None) -> bytes:
    """One closed article: a pinned realm beside a scrolling prose column.

    The realm keeps a fixed viewport and scrolls internally; the host document
    carries one `[data-cue]` section per checkpoint as the scaffold an author
    fills in. Notes never appear here: callers pass the public projection.
    """

    unsupported = unsupported_capabilities(payload)
    if unsupported:
        raise WorkspaceError(
            "PRES_EXPORT_CAPABILITY_UNSUPPORTED",
            f"checkpoint {unsupported[0][0]!r} requires capability {unsupported[0][1]!r}, which no closed document can honour",
            status=422,
        )
    if any("notes" in checkpoint and checkpoint["notes"] for checkpoint in payload.get("checkpoints", ())):
        raise WorkspaceError("PRES_PUBLIC_LEAK", "a scroll article is public; compose it from the projection", status=422)
    program = runtime_source().decode("utf-8") + "\n" + _resource(SCROLL_SHELL_KEY).decode("utf-8")
    labels = {str(item["id"]): str(item["label"]) for item in payload.get("checkpoints", ())}
    sections = "\n".join(
        f'<section data-cue="{escape(str(checkpoint_id))}" id="cue-section-{escape(str(checkpoint_id))}">'
        f"<h2>{escape(labels.get(str(checkpoint_id), str(checkpoint_id)))}</h2></section>"
        for checkpoint_id in payload.get("checkpoint_order", ())
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{escape(_shell_csp(program))}">
<title>{escape(title or str(payload.get('presentation_id', 'article')))}</title>
<meta name="doxagon-revision" content="{escape(str(payload.get('revision', '')))}">
<meta name="doxagon-runtime" content="{escape(RUNTIME_VERSION)}">
<meta name="doxagon-runtime-sha256" content="{escape(RUNTIME_SHA256)}">
<style>{_SCROLL_CSS}</style>
</head><body>
<main id="doxagon-article" data-revision="{escape(str(payload.get('revision', '')))}" data-reading-line="0.4">
<div id="doxagon-stage" aria-live="polite"></div>
<div id="doxagon-prose">
{sections}
</div>
</main>
<script type="application/json" id="doxagon-deck-payload">{embed_json(payload)}</script>
<script type="module">{program}</script>
</body></html>
"""
    return document.encode("utf-8")


def _shell_csp(program: str) -> str:
    return "; ".join(
        [
            "default-src 'none'",
            # The shell is pinned by hash; `data:` admits only the realm
            # programs, which a checkpoint realm inherits this policy for and
            # which carry the revision's own registered bytes.
            f"script-src 'sha256-{base64.b64encode(bytes.fromhex(sha256(program.encode('utf-8')))).decode('ascii')}' data:",
            "style-src 'unsafe-inline'",
            "img-src data:",
            "media-src data:",
            "font-src data:",
            "connect-src 'none'",
            "frame-src 'self' data:",
            "child-src 'self' data:",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'none'",
        ]
    )


_SHELL_CSS = """
:root { color-scheme: light dark; --deck-gap: 0.75rem; }
* { box-sizing: border-box; }
body { margin: 0; font: 16px/1.5 system-ui, sans-serif; }
#doxagon-deck { display: grid; grid-template-rows: 1fr auto; min-height: 100vh; }
#doxagon-stage { position: relative; overflow: hidden; }
#doxagon-stage iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; background: transparent; }
#doxagon-controls { display: flex; flex-wrap: wrap; gap: var(--deck-gap); align-items: center; padding: var(--deck-gap); border-top: 1px solid currentColor; }
#doxagon-controls button { min-width: 44px; min-height: 44px; font: inherit; cursor: pointer; }
#doxagon-controls .doxagon-label { font-variant-numeric: tabular-nums; }
#doxagon-controls .doxagon-error { color: #b00020; }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
"""


#: The host reserves nothing: the realm is the viewport, and the author's page
#: provides every column, margin, and background it wants.
_DOCUMENT_CSS = """
:root { color-scheme: light dark; }
html, body { margin: 0; height: 100%; }
body { overflow: hidden; }
#doxagon-stage { display: block; width: 100vw; height: 100vh; }
#doxagon-stage iframe { width: 100%; height: 100%; border: 0; display: block; }
#doxagon-status { position: fixed; inset: auto 0 0 0; margin: 0; padding: 0.25rem 0.75rem; font: 12px/1.4 system-ui, sans-serif; color: #b00020; background: Canvas; }
#doxagon-status:empty { display: none; }
"""


_SCROLL_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; font: 18px/1.6 Georgia, 'Iowan Old Style', serif; }
#doxagon-article { display: grid; grid-template-columns: minmax(0, 1fr); }
#doxagon-stage { position: sticky; top: 0; height: 100vh; overflow: hidden; background: Canvas; }
#doxagon-stage iframe { width: 100%; height: 100%; border: 0; display: block; }
#doxagon-prose { padding: 0 clamp(1rem, 4vw, 3rem); }
#doxagon-prose section { min-height: 100vh; display: grid; align-content: center; max-width: 60ch; }
#doxagon-prose h2 { font-weight: 400; font-size: clamp(1.4rem, 3vw, 2.2rem); margin: 0 0 1rem; }
@media (min-width: 900px) {
  #doxagon-article { grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); align-items: start; }
}
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; scroll-behavior: auto !important; } }
"""


def runtime_manifest() -> dict[str, Any]:
    """What a receipt or export pins about the runtime that produced a state."""

    return {
        "version": RUNTIME_VERSION,
        "runtime_sha256": RUNTIME_SHA256,
        "shell_sha256": sha256(_resource(SHELL_KEY)),
        "scroll_shell_sha256": sha256(_resource(SCROLL_SHELL_KEY)),
        "document_shell_sha256": sha256(_resource(DOCUMENT_SHELL_KEY)),
        "offline_capabilities": sorted(OFFLINE_CAPABILITIES),
    }


def source_archive_members(store: Any, revision: str) -> Iterable[tuple[str, bytes]]:
    """Every registered source, asset, and receipt byte of one revision.

    Workspace-local state — HEAD, staging, jobs, derived thumbnails, agent
    tasks — is outside the revision tree, so it cannot leak into an archive
    built from the revision's own declared members.
    """

    root = store.revision_root(revision)
    receipt = store.read_receipt(revision)
    manifest = store.read_manifest(revision)
    yield MANIFEST_KEY, canonical_json(manifest)
    for checkpoint in receipt.get("checkpoints", ()):
        for source in checkpoint.get("sources", ()):
            key = str(source["path"])
            yield key, read_contained(root, key)
    for record in manifest.get("assets", ()):
        key = f"{ASSET_ROOT}/{record['storage_key']}"
        yield key, read_contained(root, key, declared_size=int(record["bytes"]), maximum=64 * 1024 * 1024)
    yield f"receipts/{revision.split(':', 1)[1]}.validation.json", canonical_json(receipt)
