"""Public authored-document fixture shared by API and browser proofs."""
import base64
import json
from pathlib import Path

from tests.synthetic_vault import png


def write_authored_project(root: Path, slug: str = 'observatory') -> Path:
    project = root / 'projects' / slug
    directory = project / 'outputs' / 'document'
    directory.mkdir(parents=True, exist_ok=True)
    (root / 'knowledge').mkdir(exist_ok=True)
    if not (root / 'theses').exists():
        (root / 'theses').symlink_to('projects')
    (project / 'config.yaml').write_text(f'name: {slug}\ntitle: Observatory\naudience: Curious readers\ndiegesis: synthetic\n')
    fixture = Path(__file__).parent / 'fixtures' / 'documents'
    document = (fixture / 'observatory.html').read_text()
    images = []
    for i in range(10):
        image = base64.b64encode(png((i * 20, 80, 140))).decode()
        images.append(f'<img id="slot-{i}" alt="Plate {i}" src="data:image/png;base64,{image}">')
    # A reused payload and a declared cue let inspection distinguish usage from
    # bytes without making the fixture's JavaScript into static authority.
    images.append(images[0].replace('slot-0', 'slot-reused'))
    document = document.replace('</body>', '<section hidden id="plates" class="chapter"><p data-cue="cue-0">Dawn</p>' + ''.join(images) + '</section></body>')
    (directory / 'observatory.html').write_text(document)
    (directory / 'notes.json').write_bytes((fixture / 'observatory.notes.json').read_bytes())
    (directory / 'presentation.json').write_text(json.dumps({'schema': 'doxagon.authored-document/1', 'document': 'observatory.html', 'notes': 'notes.json'}))
    return project


def write_image_generation_inputs(project: Path) -> None:
    """Legacy image inputs with deliberately unverified saved history."""
    from hashlib import sha256

    def write(path, value):
        target = project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value if isinstance(value, bytes) else value.encode())

    bundle = 'outputs/presentation/slides/dawn/images/main'
    original = png((0, 80, 140))
    write(bundle + '/outputs/original.png', original)
    write(bundle + '/outputs/assembled_prompt.md', 'Saved old prompt: an astronomer under a violet sky.\n')
    write(bundle + '/outputs/generation_config.json', '{"image_size":"2K","aspect_ratio":"16:9"}')
    write(bundle + '/definition.md', '---\nstyles: [characters/astronomer]\ncustom_constraints: Keep the telescope visible.\n---\n[INK] [ASTRONOMER] [OLD_TAG] An astronomer at dawn. <script>window.promptExecuted=true</script>\n')
    write('outputs/presentation/styles/constraints/layout/definition.md', '**Tag:** `[GLOBAL]`\nNo lettering.\n')
    write('outputs/presentation/styles/paper/definition.md', '**Tag:** `[PAPER]`\nWhite paper.\n')
    write('outputs/presentation/styles/ink/definition.md', '---\nrequires: [paper]\n---\n**Tag:** `[INK]`\nFine black linework.\n')
    write('outputs/presentation/styles/characters/astronomer/definition.md', '---\nrequires: [ink]\nsources: [astronomer.png]\n---\n**Tag:** `[ASTRONOMER]`\nA long coat and round spectacles.\n')
    write('outputs/presentation/styles/characters/astronomer/sources/astronomer.png', png((10, 20, 30)))
    write('outputs/document/assets.json', json.dumps({'assets': [{
        'source': f'projects/{project.name}/{bundle}/outputs/original.png',
        'source_sha256': sha256(original).hexdigest(), 'embedded_sha256': sha256(original).hexdigest(),
    }]}))
