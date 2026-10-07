"""Token-addressed image slots; edits never search-and-replace payload text."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from io import BytesIO
import re

from PIL import Image, __version__ as pillow_version

from .document_inspection import MAX_HTML, MAX_PIXELS, VOID, sha
from .project import DocumentWorkspaceError


def refuse(message: str):
    raise DocumentWorkspaceError('DOCUMENT_IMAGE_STRUCTURE', message)


@dataclass
class Element:
    tag: str
    attrs: dict
    start: int
    opening_end: int
    end: int = 0
    closing_start: int = 0
    parent: Element | None = None

    def inside(self, element: Element) -> bool:
        return element.start < self.start < element.end


class ImageDocument(HTMLParser):
    def __init__(self, raw: bytes):
        super().__init__(convert_charrefs=True)
        if len(raw) > MAX_HTML:
            refuse('HTML exceeds the delivery limit')
        self.source = raw.decode('utf-8')
        self.lines = [0]
        for line in self.source.splitlines(keepends=True):
            self.lines.append(self.lines[-1] + len(line))
        self.elements: list[Element] = []
        self.stack: list[Element] = []
        self.feed(self.source)
        self.close()
        containers = [e for e in self.elements if e.attrs.get('id') == 'dox-asset-payloads']
        if len(containers) > 1 or containers and not containers[0].end:
            refuse('Expected one closed progressive payload container')
        self.container = containers[0] if containers else None
        self.slots = [e for e in self.elements if e.tag == 'img' and not (self.container and e.inside(self.container))]
        ids = [e.attrs['id'] for e in self.elements if e.attrs.get('id')]
        if len(ids) != len(set(ids)):
            refuse('Duplicate element IDs prevent stable targeting')
        self.payloads: dict[str, tuple[str, str]] = {}
        if self.container:
            children = [e for e in self.elements if e.parent is self.container]
            if len(children) % 2:
                refuse('Progressive payloads must be figure/receive pairs')
            for figure, script in zip(children[::2], children[1::2]):
                key = figure.attrs.get('data-dox-source')
                text = self.source[script.opening_end:script.closing_start]
                if figure.tag != 'figure' or not key or key in self.payloads or script.tag != 'script' or re.sub(r'\s+', '', text) != 'window.doxagonAssets.receive(document.currentScript.previousElementSibling);':
                    refuse('Unsupported progressive payload envelope')
                images = [e for e in self.elements if e.tag == 'img' and e.inside(figure)]
                if len(images) != 1 or not figure.end or not script.end:
                    refuse('Each payload requires one image and a closed receive script')
                url = images[0].attrs.get('src', '')
                decode_image(url)
                self.payloads[key] = (url, self.source[figure.start:script.end] + '\n')
            sentinel = [e for e in self.elements if e.tag == 'script' and e.start >= self.container.end and re.sub(r'\s+', '', self.source[e.opening_end:e.closing_start]) == 'window.doxagonAssets.complete();']
            if len(sentinel) != 1:
                refuse('Expected one completion sentinel after the payload container')
        for slot in self.slots:
            self.url(slot)  # Missing or dynamic slots block automatic replacement.

    def position(self) -> int:
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if len(self.elements) >= 100_000 or len(dict(attrs)) != len(attrs):
            refuse('Ambiguous or oversized HTML structure')
        start = self.position()
        element = Element(tag, dict(attrs), start, start + len(self.get_starttag_text()), parent=self.stack[-1] if self.stack else None)
        self.elements.append(element)
        if tag in VOID:
            element.end = element.opening_end
        else:
            self.stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            element = self.stack.pop()
            element.end = element.opening_end

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                element = self.stack[index]
                element.closing_start = self.position()
                element.end = self.source.index('>', self.position()) + 1
                del self.stack[index:]
                return

    def url(self, slot: Element) -> str:
        key = slot.attrs.get('data-dox-asset')
        if key:
            if key not in self.payloads or slot.attrs.get('src'):
                refuse('Missing payload or mixed inline/progressive slot')
            return self.payloads[key][0]
        url = slot.attrs.get('src', '')
        decode_image(url)
        return url

    def digest(self, slot: Element) -> str:
        return sha(decode_image(self.url(slot))[0])

    def edit(self, edits: list[tuple[int, int, str]]) -> bytes:
        source = self.source
        last = len(source)
        for start, end, replacement in sorted(edits, reverse=True):
            if end > last:
                refuse('Overlapping image edits')
            source = source[:start] + replacement + source[end:]
            last = start
        raw = source.encode()
        if len(raw) > MAX_HTML:
            refuse('Replacement exceeds the 32 MiB delivery limit')
        return raw


def decode_image(url: str) -> tuple[bytes, str]:
    try:
        media, encoded = url.split(';base64,', 1)
        if media not in {'data:image/png', 'data:image/jpeg', 'data:image/webp', 'data:image/gif'}:
            raise ValueError()
        return base64.b64decode(re.sub(r'\s+', '', encoded), validate=True), media[5:]
    except (ValueError, AttributeError):
        refuse('Image slots must resolve to embedded raster bytes')


def image_tag(attrs: dict) -> str:
    return '<img ' + ' '.join(escape(key) if value is None else f'{escape(key)}="{escape(str(value), quote=True)}"' for key, value in attrs.items()) + '>'


def adopt_slots(raw: bytes) -> tuple[bytes, dict[str, str]]:
    document = ImageDocument(raw)
    edits = []
    used = {e.attrs.get('id') for e in document.elements}
    slots = {}
    for index, slot in enumerate(document.slots):
        identity = slot.attrs.get('id')
        if not identity:
            identity = f'dox-image-{index + 1}'
            while identity in used:
                identity += '-image'
            used.add(identity)
            edits.append((slot.start, slot.opening_end, image_tag({**slot.attrs, 'id': identity})))
        slots[identity] = document.digest(slot)
    return document.edit(edits), slots


def encode_variant(raw: bytes, *, quality: int = 88) -> tuple[bytes, dict]:
    if not isinstance(quality, int) or not 1 <= quality <= 100:
        refuse('WebP quality must be 1..100')
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > MAX_PIXELS or getattr(image, 'n_frames', 1) != 1:
                refuse('Image exceeds pixel limits or is animated')
            image.load()
            output = BytesIO()
            image.convert('RGBA' if 'A' in image.getbands() else 'RGB').save(output, 'WEBP', quality=quality, method=6)
            encoded = output.getvalue()
            receipt = {'original_sha256': sha(raw), 'embedded_sha256': sha(encoded), 'encoder': 'Pillow',
                       'version': pillow_version, 'format': 'webp', 'quality': quality, 'method': 6,
                       'width': image.width, 'height': image.height}
            return encoded, receipt
    except (OSError, Image.DecompressionBombError) as error:
        refuse(f'Unsupported original raster: {error}')


SLOT_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,127}')
DATA_IMAGE = re.compile(r'data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=\s]*')


def add_slots(raw: bytes, container: str, slots: list[dict]) -> bytes:
    """Append new stable slots, each with its own encoded bytes, inside an existing element.

    The container is ordinary document structure added beforehand by a text patch; existing slots and
    payloads must come through byte for byte, so this is the only way new image bytes enter by insertion.
    """
    if not slots:
        refuse('Name at least one new slot')
    document = ImageDocument(raw)
    targets = [e for e in document.elements if e.attrs.get('id') == container]
    if len(targets) != 1:
        refuse(f'No element with id {container!r} to hold the new slots')
    target = targets[0]
    if target.tag in VOID or not target.closing_start:
        refuse('The slot container must be an element with a closing tag')
    if document.container and (target is document.container or target.inside(document.container)):
        refuse('New slots cannot be placed in the progressive payload container')
    used = {e.attrs['id'] for e in document.elements if e.attrs.get('id')}
    markup, added = '', {}
    for slot in slots:
        identity = slot['id']
        if not isinstance(identity, str) or not SLOT_ID.fullmatch(identity) or identity in used:
            refuse(f'Slot id {identity!r} is invalid or already used in the document')
        used.add(identity)
        added[identity] = sha(slot['encoded'])
        url = 'data:image/webp;base64,' + base64.b64encode(slot['encoded']).decode()
        markup += '\n' + image_tag({'id': identity, 'alt': slot.get('alt', ''), 'src': url})
    result = document.edit([(target.closing_start, target.closing_start, markup + '\n')])
    verified = ImageDocument(result)
    before = [(s.attrs.get('id'), document.digest(s), s.attrs) for s in document.slots]
    after = [(s.attrs.get('id'), verified.digest(s), s.attrs) for s in verified.slots if s.attrs.get('id') not in added]
    fresh = {s.attrs.get('id'): verified.digest(s) for s in verified.slots if s.attrs.get('id') in added}
    if before != after or fresh != added or list(verified.payloads) != list(document.payloads):
        refuse('Adding slots changed existing slots or payloads')
    return result


def payloads_preserved(before: bytes, after: bytes) -> bool:
    """True when every slot keeps its id and bytes and no embedded image appears or disappears."""
    try:
        old, new = ImageDocument(before), ImageDocument(after)
        slots = lambda doc: [(s.attrs.get('id'), doc.digest(s)) for s in doc.slots]  # noqa: E731
        urls = lambda raw: sorted(re.sub(r'\s+', '', url) for url in DATA_IMAGE.findall(raw.decode('utf-8')))  # noqa: E731
        return slots(old) == slots(new) and list(old.payloads) == list(new.payloads) and urls(before) == urls(after)
    except DocumentWorkspaceError:
        return False


def replace_slots(raw: bytes, expected: dict[str, str], encoded: bytes) -> bytes:
    if not expected:
        refuse('Name at least one stable image slot')
    document = ImageDocument(raw)
    actual = {slot.attrs.get('id'): slot for slot in document.slots if slot.attrs.get('id')}
    for identity, digest in expected.items():
        if identity not in actual or document.digest(actual[identity]) != digest:
            refuse(f'Slot {identity} is missing or has a different payload')
    url = 'data:image/webp;base64,' + base64.b64encode(encoded).decode()
    key = 'asset-' + sha(encoded)
    edits = []
    ordered = {}
    for slot in document.slots:
        attrs = dict(slot.attrs)
        if attrs.get('id') in expected:
            if attrs.get('data-dox-asset'):
                attrs['data-dox-asset'] = key
            else:
                attrs['src'] = url
            edits.append((slot.start, slot.opening_end, image_tag(attrs)))
        payload_key = attrs.get('data-dox-asset')
        if payload_key and payload_key not in ordered:
            if payload_key == key:
                payload_attrs = {'src': url, 'loading': 'lazy', 'alt': attrs.get('alt', '')}
                for dimension in ('width', 'height'):
                    if dimension in attrs:
                        payload_attrs[dimension] = attrs[dimension]
                ordered[key] = f'<figure data-dox-source="{key}">{image_tag(payload_attrs)}<figcaption>{escape(attrs.get("alt", ""))}</figcaption></figure>\n<script>window.doxagonAssets.receive(document.currentScript.previousElementSibling);</script>\n'
            else:
                ordered[payload_key] = document.payloads[payload_key][1]
    if document.container:
        edits.append((document.container.opening_end, document.container.closing_start, '\n' + ''.join(ordered.values())))
    result = document.edit(edits)
    verified = ImageDocument(result)
    if len(document.slots) != len(verified.slots):
        refuse('Image edit changed slot count')
    for before, after in zip(document.slots, verified.slots, strict=True):
        identity = before.attrs.get('id')
        if verified.digest(after) != (sha(encoded) if identity in expected else document.digest(before)):
            refuse('Image edit affected an unexpected slot')
        def unchanged(attrs):
            return {k: v for k, v in attrs.items() if k not in {'src', 'data-dox-asset'}}
        if unchanged(before.attrs) != unchanged(after.attrs):
            refuse('Image edit changed slot geometry or attributes')
    return result
