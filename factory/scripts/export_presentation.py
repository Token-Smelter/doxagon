#!/usr/bin/env python3
"""Export a presentation with all necessary components."""

import os
import shutil
import tempfile
import yaml
import re
from pathlib import Path
from datetime import date

def extract_doxai_from_diegesis(diegesis_path: Path) -> set[str]:
    """Extract all doxai IDs from a diegesis file."""
    content = diegesis_path.read_text()
    return set(re.findall(r'- (d-[\w-]+)', content))

def extract_evidence_from_doxai(doxai_dir: Path, doxai_ids: set[str]) -> set[str]:
    """Extract evidence IDs referenced by doxai."""
    evidence_ids = set()
    for doxa_id in doxai_ids:
        doxa_path = doxai_dir / f"{doxa_id}.md"
        if doxa_path.exists():
            content = doxa_path.read_text()
            evidence_ids.update(re.findall(r'- (e-[\w-]+)', content))
    return evidence_ids

def get_selected_image(slide_md_path: Path) -> str | None:
    """Get the selected image path from slide.md."""
    if not slide_md_path.exists():
        return None
    content = slide_md_path.read_text()
    match = re.search(r'selected:\s*(\S+)', content)
    if match and match.group(1) != 'null':
        return match.group(1)
    return None

def tag_doxa(src_path: Path, dst_path: Path, presentation: str, export_date: str):
    """Copy doxa file with export tag injected."""
    content = src_path.read_text()
    lines = content.split('\n')
    
    # Insert export tag after first ---
    if lines[0] == '---':
        lines.insert(1, f'export:')
        lines.insert(2, f'  presentation: {presentation}')
        lines.insert(3, f'  date: {export_date}')
    
    dst_path.write_text('\n'.join(lines))

def extract_edges(logos_path: Path, doxai_ids: set[str], presentation: str, export_date: str) -> str:
    """Extract edges that connect doxai in the export set."""
    with open(logos_path) as f:
        data = yaml.safe_load(f)
    
    filtered = []
    for edge in data.get('edges', []):
        if edge.get('source') in doxai_ids and edge.get('target') in doxai_ids:
            filtered.append(edge)
    
    output = {
        'export': {
            'presentation': presentation,
            'date': export_date,
            'note': 'Subset of logos.yaml containing only edges within this presentation'
        },
        'edges': filtered
    }
    
    return yaml.dump(output, default_flow_style=False, sort_keys=False, allow_unicode=True)

def export_presentation(thesis_name: str, project_root: Path, output_path: Path):
    """Export a complete presentation package."""
    export_date = date.today().isoformat()
    thesis_dir = project_root / 'theses' / thesis_name
    library_dir = project_root / 'library'
    
    # Load config to get diegesis name
    config_path = thesis_dir / 'config.yaml'
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    diegesis_name = config.get('diegesis', f'n-{thesis_name}')
    diegesis_path = library_dir / 'diegeses' / f'{diegesis_name}.md'
    
    # Create temp staging directory
    staging = Path(tempfile.mkdtemp())
    print(f"Staging to: {staging}")
    
    # 1. Copy thesis structure
    thesis_staging = staging / 'theses' / thesis_name
    thesis_staging.mkdir(parents=True)
    
    for f in ['CLAUDE.md', 'config.yaml']:
        src = thesis_dir / f
        if src.exists():
            shutil.copy2(src, thesis_staging / f)
    
    # Copy thesis/
    thesis_content = thesis_dir / 'thesis'
    if thesis_content.exists():
        shutil.copytree(thesis_content, thesis_staging / 'thesis')
    
    # 2. Copy presentation config
    pres_dir = thesis_dir / 'outputs' / 'presentation'
    pres_staging = thesis_staging / 'outputs' / 'presentation'
    pres_staging.mkdir(parents=True)
    
    pres_config = pres_dir / 'config.yaml'
    if pres_config.exists():
        shutil.copy2(pres_config, pres_staging / 'config.yaml')
    
    # 3. Copy slides with selected images
    slides_dir = pres_dir / 'slides'
    slides_staging = pres_staging / 'slides'
    
    for slide_dir in sorted(slides_dir.iterdir()):
        if not slide_dir.is_dir():
            continue
        
        slide_staging = slides_staging / slide_dir.name
        slide_staging.mkdir(parents=True)
        
        # Copy slide.md
        slide_md = slide_dir / 'slide.md'
        if slide_md.exists():
            shutil.copy2(slide_md, slide_staging / 'slide.md')
        
        # Copy images/{id}/definition.md and selected image
        images_dir = slide_dir / 'images'
        if images_dir.exists():
            for img_bundle in images_dir.iterdir():
                if not img_bundle.is_dir():
                    continue
                
                bundle_staging = slide_staging / 'images' / img_bundle.name
                bundle_staging.mkdir(parents=True)
                
                # Copy definition.md
                defn = img_bundle / 'definition.md'
                if defn.exists():
                    shutil.copy2(defn, bundle_staging / 'definition.md')
                
                # Copy selected image
                selected = get_selected_image(slide_md)
                if selected:
                    src_img = img_bundle / selected
                    if src_img.exists():
                        # Create outputs dir and copy
                        (bundle_staging / 'outputs').mkdir(exist_ok=True)
                        shutil.copy2(src_img, bundle_staging / selected)
                        print(f"  Copied selected: {slide_dir.name}/{selected}")
    
    # 4. Copy styles (definition.md + source exemplars)
    styles_dir = pres_dir / 'styles'
    if styles_dir.exists():
        styles_staging = pres_staging / 'styles'
        for root, dirs, files in os.walk(styles_dir):
            rel_root = Path(root).relative_to(styles_dir)
            dst_root = styles_staging / rel_root
            dst_root.mkdir(parents=True, exist_ok=True)
            
            for f in files:
                # Copy definition.md and source images
                if f == 'definition.md' or (Path(root).name == 'sources' and f.endswith(('.png', '.jpg', '.jpeg'))):
                    shutil.copy2(Path(root) / f, dst_root / f)
    
    # 5. Copy library components
    lib_staging = staging / 'library'
    
    # Diegesis
    (lib_staging / 'diegeses').mkdir(parents=True)
    shutil.copy2(diegesis_path, lib_staging / 'diegeses' / diegesis_path.name)
    
    # Get doxai IDs
    doxai_ids = extract_doxai_from_diegesis(diegesis_path)
    print(f"Found {len(doxai_ids)} doxai in diegesis")
    
    # Copy doxai with export tags
    (lib_staging / 'doxai').mkdir(parents=True)
    for doxa_id in doxai_ids:
        src = library_dir / 'doxai' / f'{doxa_id}.md'
        if src.exists():
            dst = lib_staging / 'doxai' / f'{doxa_id}.md'
            tag_doxa(src, dst, thesis_name, export_date)
        else:
            print(f"  Warning: Missing doxa {doxa_id}")
    
    # Get and copy evidence
    evidence_ids = extract_evidence_from_doxai(library_dir / 'doxai', doxai_ids)
    if evidence_ids:
        (lib_staging / 'evidence').mkdir(parents=True)
        for ev_id in evidence_ids:
            src = library_dir / 'evidence' / f'{ev_id}.md'
            if src.exists():
                shutil.copy2(src, lib_staging / 'evidence' / f'{ev_id}.md')
        print(f"Copied {len(evidence_ids)} evidence files")
    
    # Extract edges
    logos_yaml = extract_edges(library_dir / 'logos.yaml', doxai_ids, thesis_name, export_date)
    (lib_staging / 'logos.yaml').write_text(logos_yaml)
    edge_count = logos_yaml.count('source:')
    print(f"Extracted {edge_count} edges")
    
    # 6. Create zip
    shutil.make_archive(str(output_path.with_suffix('')), 'zip', staging)
    print(f"\nCreated: {output_path}")
    
    # Cleanup
    shutil.rmtree(staging)
    
    return output_path

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: export_presentation.py <thesis-name> [output-path]")
        sys.exit(1)
    
    thesis_name = sys.argv[1]
    project_root = Path(__file__).parent.parent.parent if Path(__file__).parent.name == 'scripts' else Path.cwd()
    
    output_name = f"{thesis_name}-{date.today().strftime('%Y%m%d')}.zip"
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd() / output_name
    
    export_presentation(thesis_name, project_root, output_path)
