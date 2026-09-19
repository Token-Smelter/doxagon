"""Validate authored postimages in an isolated browser before promotion."""
from __future__ import annotations

from html.parser import HTMLParser
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

from .document_inspection import Inspection, MAX_HTML, sha
from .project import DocumentWorkspaceError

PROBE = r"""html => new Promise((resolve, reject) => {
    const frame = document.querySelector('iframe');
    let ready = null;
    const timer = setTimeout(() => reject(new Error('No compatible document bridge')), 10000);
    frame.onload = () => {
        const channel = new MessageChannel();
        channel.port1.onmessage = ({data}) => {
            if (data?.type === 'ready') ready = data;
            if (data?.type === 'position' && ready) {
                clearTimeout(timer);
                window.validationPort = channel.port1;
                window.validationReady = ready;
                window.validationPosition = data;
                channel.port1.onmessage = ({data}) => {
                    if (data?.type === 'position') window.validationPosition = data;
                };
                resolve({ready, position: data});
            }
        };
        frame.contentWindow.postMessage({type:'doxagon:connect'}, '*', [channel.port2]);
    };
    frame.srcdoc = html;
})"""


def validation_identity() -> dict:
    """Bind a proof to the implementation and built player that checked it."""
    root = Path(__file__).resolve().parents[3]
    package = Path(__file__).resolve().parents[1]
    sources = sorted((package / 'renderings').glob('document_*.py'))
    sources += [package / 'renderings/project.py', package / 'wal.py']
    manifest = root / 'apps/web/frontend/build/.doxagon-source-manifest.json'
    return {'source_sha256': sha(json.dumps({str(path.relative_to(package)): sha(path.read_bytes()) for path in sources}, sort_keys=True).encode()),
            'frontend_manifest_sha256': sha(manifest.read_bytes()) if manifest.is_file() else None}


def browser_probe(path: Path) -> dict:
    """Worker entry: no vault authority, network, or private notes in the frame."""
    from playwright.sync_api import sync_playwright
    requests = []
    with sync_playwright() as browser_api:
        browser = browser_api.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1100, 'height': 720}, reduced_motion='reduce')
        # Fulfil the host in-process: a secure synthetic origin supplies the
        # same Web Crypto availability as the real HTTPS/loopback player.
        # No DNS request or outside connection is made, including by the frame.
        host = 'https://doxagon-validation.invalid/'
        def route_request(route):
            if route.request.url == host and route.request.is_navigation_request():
                route.fulfill(content_type='text/html', body='<iframe sandbox="allow-scripts" style="width:100%;height:650px"></iframe>')
            else:
                requests.append('blocked')
                route.abort()
        context.route('**/*', route_request)
        page = context.new_page()
        page.goto(host)
        result = page.evaluate(PROBE, path.read_text())
        ready = result.get('ready', {})
        cues = ready.get('cues')
        if not isinstance(cues, list) or not 1 <= len(cues) <= 1000:
            raise ValueError('Invalid runtime cue map')
        identifiers = []
        for cue in cues:
            if not isinstance(cue, dict) or not all(isinstance(cue.get(key), str) and 0 < len(cue[key]) <= 1000 for key in ['id', 'title']):
                raise ValueError('Invalid runtime cue')
            identifiers.append(cue['id'])
        if len(set(identifiers)) != len(identifiers):
            raise ValueError('Duplicate runtime cues')
        if not all(isinstance(ready.get(key), str) and 0 < len(ready[key]) <= 1000 for key in ['documentId', 'edition']):
            raise ValueError('Invalid runtime identity')

        def position_valid(position):
            index, progress = position.get('index'), position.get('progress')
            if (position.get('documentId') != ready['documentId'] or position.get('edition') != ready['edition']
                    or type(index) is not int or not 0 <= index < len(cues) or position.get('cue') != identifiers[index]
                    or position.get('total') != len(cues) or type(progress) not in {int, float} or not math.isfinite(progress) or not 0 <= progress <= 1):
                raise ValueError('Runtime position disagrees with the declared bridge contract')
        position_valid(result['position'])
        for cue in [identifiers[-1], identifiers[0]]:
            page.evaluate("cue => window.validationPort.postMessage({type:'go', cue})", cue)
            page.wait_for_function('cue => window.validationPosition?.cue === cue', arg=cue, timeout=5000)
            position_valid(page.evaluate('window.validationPosition'))
        frame = next(frame for frame in page.frames if frame.parent_frame)
        assets = frame.evaluate('window.doxagonAssets?.state?.() ?? null')
        if assets and (not assets.get('complete') or assets.get('interrupted') or assets.get('received') != assets.get('total')):
            raise ValueError('Progressive image payloads did not complete')
        if requests:
            raise ValueError('The document attempted to load external dependencies')
        browser.close()
    return {'documentId': ready['documentId'], 'edition': ready['edition'], 'cues': cues,
            'navigation': 'first-and-last', 'assets': assets, 'external_requests': 0}


class CuePlacement(HTMLParser):
    """Where each source `data-cue` element sits relative to the bridge script.

    A bridge collects its cue list when the script runs, so an element that
    starts after that script is never in it. The source order then matches the
    notes exactly while the runtime reports fewer cues, and every obvious check
    passes. Recording the placement lets the failure name that cause.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.after_script = False
        self.cues: list[tuple[str, bool]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        data = dict(attrs)
        if data.get('data-cue') and len(self.cues) < 1000:
            self.cues.append((data['data-cue'][:1000], self.after_script))
        if tag == 'script':
            self.after_script = True


def source_cues(raw: bytes) -> list[tuple[str, bool]]:
    parser = CuePlacement()
    parser.feed(raw.decode('utf-8', errors='replace'))
    parser.close()
    return parser.cues


def unreachable_cues(document: bytes | None, reported: list[str]) -> list[str]:
    """Source cues the runtime never saw because they follow its script."""
    if document is None:
        return []
    return [cue for cue, after_script in source_cues(document) if after_script and cue not in reported]


def notes_disagreement(raw: bytes, proof: dict, document: bytes | None = None) -> str | None:
    """Name which disagreement DOCUMENT_NOTES_MISMATCH is reporting.

    The code covers several distinct conditions. Returning the identifying
    detail - the differing values, the cue ids and the side they are missing
    from, or the offending cue - keeps the first failure actionable. When the
    document is supplied, a cue the notes declare and the runtime omitted is
    also checked against its position in the source, because a section placed
    after the bridge script is invisible to the runtime while still matching
    the notes in source order.
    """
    try:
        notes = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        return f'Notes are not valid JSON: {error}'
    if not isinstance(notes, dict):
        return f'Notes must be a JSON object, not {type(notes).__name__}'
    for key in ('documentId', 'edition'):
        if notes.get(key) != proof[key]:
            return f'Notes {key} {notes.get(key)!r} disagrees with the document {key} {proof[key]!r}'
    cues = notes.get('cues', [])
    if not isinstance(cues, list) or not all(isinstance(cue, dict) for cue in cues):
        return f'Notes cues must be a list of objects, not {type(cues).__name__}'
    declared = [cue.get('id') for cue in cues]
    reported = [cue['id'] for cue in proof['cues']]
    if declared != reported:
        absent_from_notes = [cue for cue in reported if cue not in declared]
        absent_from_document = [cue for cue in declared if cue not in reported]
        parts = []
        if absent_from_notes:
            parts.append('missing from the notes: ' + ', '.join(repr(cue) for cue in absent_from_notes))
        if absent_from_document:
            parts.append('in the notes but not reported by the document: ' + ', '.join(repr(cue) for cue in absent_from_document))
        if not parts:
            parts.append(f'ordered {declared} in the notes and {reported} in the document')
        unreachable = [cue for cue in unreachable_cues(document, reported) if cue in absent_from_document]
        if unreachable:
            parts.append('the element carrying data-cue="' + unreachable[0] + '" appears after the <script> that builds '
                         'the cue list, so the runtime never saw ' + ('them' if len(unreachable) > 1 else 'it')
                         + '; move those sections above the script')
        return 'Notes cues disagree with the document: ' + '; '.join(parts)
    for cue in cues:
        if not isinstance(cue.get('notes'), str):
            return f'Notes body for cue {cue.get("id")!r} is {type(cue.get("notes")).__name__}, not a string'
    return None


def validate_html(raw: bytes) -> dict:
    if not raw or len(raw) > MAX_HTML:
        raise DocumentWorkspaceError('DOCUMENT_VALIDATION_FAILED', 'HTML must fit the 32 MiB delivery limit')
    with tempfile.TemporaryDirectory(prefix='doxagon-document-check-') as scratch:
        path = Path(scratch) / 'candidate.html'
        path.write_bytes(raw)
        try:
            process = subprocess.run([sys.executable, '-m', __name__, '--probe', str(path)],
                                     capture_output=True, timeout=40, check=False)
            if process.returncode:
                raise ValueError(process.stderr.decode(errors='replace')[-1500:])
            proof = json.loads(process.stdout)
        except (ValueError, subprocess.TimeoutExpired) as error:
            raise DocumentWorkspaceError('DOCUMENT_VALIDATION_FAILED', str(error)) from error
    return {'html_sha256': sha(raw), 'validator_sha256': sha(Path(__file__).read_bytes()), 'implementation': validation_identity(), **proof}


def validate_change(view: Inspection, payloads: dict[Path, bytes]) -> dict:
    from .document_changes import REGISTRY_PATH, parse_registry
    registry_path = view.project.path(REGISTRY_PATH)
    if registry_path in payloads:
        parse_registry(payloads[registry_path])
    document_path = view.project.vault / view.summary['document']['path']
    notes_item = view.summary['notes']
    notes_path = view.project.vault / notes_item['path'] if notes_item else None
    if document_path not in payloads and notes_path not in payloads:
        return {'html_sha256': view.summary['document']['sha256'], 'html_changed': False}
    raw = payloads.get(document_path, view.contents[view.summary['document']['id']])
    proof = validate_html(raw)
    notes_raw = payloads.get(notes_path, view.contents.get(notes_item['id'])) if notes_item else None
    if notes_raw is not None:
        disagreement = notes_disagreement(notes_raw, proof, raw)
        if disagreement is not None:
            raise DocumentWorkspaceError('DOCUMENT_NOTES_MISMATCH', disagreement)
        proof['notes_sha256'] = sha(notes_raw)
    return proof


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--probe':
        raise SystemExit('This worker is invoked by dox document validation')
    try:
        print(json.dumps(browser_probe(Path(sys.argv[2]))))
    except Exception as error:
        raise SystemExit(str(error)) from error
