"""Prove legacy adoption and explicit image selection in a disposable project copy."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    from doxagon.renderings.document_assets import plan_adopt_bundle, plan_bind_slots, plan_select_image
    from doxagon.renderings.document_changes import apply_plan, registry
    from doxagon.renderings.document_images import ImageDocument, adopt_slots
    from doxagon.renderings.document_inspection import inspect_document, sha
    from doxagon.renderings.document_validation import validate_change
    from doxagon.renderings.project import resolve_document_project
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', type=Path, required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = resolve_document_project(args.project, cwd=args.vault, environ={'DOXAGON_ROOT': str(args.vault)})
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / 'projects').mkdir()
    (root / 'knowledge').mkdir()
    (root / 'theses').symlink_to('projects')
    shutil.copytree(source.root, root / 'projects' / source.slug)
    project = resolve_document_project(args.project, cwd=root, environ={})
    view = inspect_document(project)
    html = project.vault / view.summary['document']['path']
    notes = project.vault / view.summary['notes']['path']
    before, notes_before = html.read_bytes(), notes.read_bytes()
    first = next(item for item in view.items if item['kind'] == 'image' and item.get('provenance') == 'verified_hash_pair')
    original = next(item for item in view.items if item['id'] == first['original'])
    bundle = str(Path(original['path']).parent.parent.relative_to('projects/' + project.slug))
    plan = plan_adopt_bundle(view, 'proof-plate', bundle)
    apply_plan(project, plan)
    assert html.read_bytes() == before and notes.read_bytes() == notes_before
    assert all((project.vault / old).read_bytes() == (project.vault / new['path']).read_bytes() for old, new in plan['details']['files'].items())
    assert not plan_adopt_bundle(inspect_document(project), 'proof-plate', bundle)['changes']
    _, slots = adopt_slots(before)
    slot = next(key for key, digest in slots.items() if digest == first['sha256'])
    apply_plan(project, plan_bind_slots(inspect_document(project), {slot: 'proof-plate'}))
    view = inspect_document(project)
    variants = registry(view)['assets']['proof-plate']['variants']
    variant = next(key for key, value in variants.items() if value['sha256'] == original['sha256'])
    apply_plan(project, plan_select_image(view, 'proof-plate', variant, [slot]))
    view = inspect_document(project)
    old, new = ImageDocument(before), ImageDocument(html.read_bytes())
    changed = [i for i, (a, b) in enumerate(zip(old.slots, new.slots)) if old.digest(a) != new.digest(b)]
    assert len(old.slots) == len(new.slots) and len(changed) == 1 and notes.read_bytes() == notes_before
    proof = validate_change(view, {html: html.read_bytes()})
    report = {'original_html_sha256': sha(before), 'changed_html_sha256': sha(html.read_bytes()), 'notes_unchanged': True,
              'slot': slot, 'adopted_files': len(plan['details']['files']), 'source_bundle': bundle,
              'registered_variants': len(variants), 'image_usages': len(new.slots), 'images': sum(item['kind'] == 'image' for item in view.items),
              'validation': proof}
    (root / 'proof.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({**report, 'validation': {key: value for key, value in proof.items() if key != 'cues'}}, indent=2))


if __name__ == '__main__':
    main()
