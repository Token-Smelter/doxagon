#!/usr/bin/env python3
"""
Migrate slide directories from numbered format to semantic slugs.

Migrates from:
    slides/05-mcluhan-medium-environment/
    slides/05-5-extensions-of-man/
    slides/06-what-is-being-extended/

To:
    slides/mcluhan-medium-environment/
    slides/extensions-of-man/
    slides/what-is-being-extended/

With order defined in config.yaml:
    slides:
      - mcluhan-medium-environment
      - extensions-of-man
      - what-is-being-extended

Usage:
    # Dry-run (default)
    python3 factory/scripts/migrate_to_semantic_slugs.py --presentation sample-editorial

    # Execute migration
    python3 factory/scripts/migrate_to_semantic_slugs.py --presentation sample-editorial --execute

    # Rollback
    python3 factory/scripts/migrate_to_semantic_slugs.py --presentation sample-editorial --rollback
"""

import argparse
import shutil
import yaml
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils import (
    get_presentation_path,
    get_presentation_output_paths,
    natural_sort_key,
    normalize_slug,
    load_output_config,
)


class MigrationError(Exception):
    """Base exception for migration errors."""
    pass


class ConflictError(MigrationError):
    """Duplicate slugs or other conflicts."""
    def __init__(self, message: str, conflicts: list = None):
        super().__init__(message)
        self.conflicts = conflicts or []


class ValidationError(MigrationError):
    """Pre/post validation failures."""
    def __init__(self, message: str, failures: list = None):
        super().__init__(message)
        self.failures = failures or []


def extract_slug(dirname: str) -> str:
    """Extract semantic slug from numbered directory name.

    Examples:
        '05-mcluhan-medium-environment' -> 'mcluhan-medium-environment'
        '05-5-extensions-of-man' -> 'extensions-of-man'
        '00-title' -> 'title'
        'already-semantic' -> 'already-semantic'
    """
    return normalize_slug(dirname)


def preflight_checks(slides_dir: Path, verbose: bool = False) -> dict:
    """Validate before migration.

    Checks:
    - No duplicate slugs after extraction
    - All directories match pattern or are already semantic

    Returns:
        dict with 'slugs' and 'mapping' (dirname -> slug)

    Raises:
        ConflictError: If duplicate slugs found
    """
    if verbose:
        print("\n[Pre-flight Checks]")

    slug_to_dirs = {}
    dirs = []
    mapping = {}

    for d in sorted(slides_dir.iterdir(), key=lambda x: natural_sort_key(x.name)):
        if not d.is_dir():
            continue

        slug = extract_slug(d.name)

        # Track for duplicate detection
        if slug not in slug_to_dirs:
            slug_to_dirs[slug] = []
        slug_to_dirs[slug].append(d.name)

        dirs.append(d.name)
        mapping[d.name] = slug

    # Check for duplicates
    conflicts = [(slug, dir_list) for slug, dir_list in slug_to_dirs.items() if len(dir_list) > 1]

    if conflicts:
        error_msg = "Duplicate slugs found:\n"
        for slug, dir_list in conflicts:
            error_msg += f"  '{slug}' would be created by: {', '.join(dir_list)}\n"
        raise ConflictError(error_msg, conflicts)

    if verbose:
        print(f"  ✓ No conflicts ({len(dirs)} unique slugs)")

    return {
        'slugs': list(slug_to_dirs.keys()),
        'mapping': mapping,
    }


def generate_slides_list(slides_dir: Path) -> list[str]:
    """Generate ordered slides list using natural sort.

    Returns:
        List of semantic slugs in presentation order
    """
    dirs = [d for d in slides_dir.iterdir() if d.is_dir()]
    dirs.sort(key=lambda d: natural_sort_key(d.name))
    return [extract_slug(d.name) for d in dirs]


def migrate_acts(acts: list[dict], slides_list: list[str], verbose: bool = False) -> list[dict]:
    """Convert act slide numbers to slugs.

    Before: slides: [1, 2, 3]
    After:  slides: ['title', 'opening-question', 'next-step']

    Args:
        acts: List of act dicts from config
        slides_list: Ordered list of slide slugs
        verbose: Print migration details

    Returns:
        List of migrated act dicts

    Raises:
        ValidationError: If act references invalid slide number
    """
    if verbose:
        print("\n[Migrating Acts]")

    migrated = []
    for act in acts:
        act_name = act.get('name', 'Unnamed')
        slide_refs = act.get('slides', [])

        migrated_refs = []
        for ref in slide_refs:
            if isinstance(ref, int):
                # 1-based position -> slug
                idx = ref - 1
                if 0 <= idx < len(slides_list):
                    migrated_refs.append(slides_list[idx])
                    if verbose:
                        print(f"  {act_name}: {ref} -> '{slides_list[idx]}'")
                else:
                    raise ValidationError(
                        f"Act '{act_name}' references slide {ref} but only {len(slides_list)} slides exist"
                    )
            else:
                # Already a slug, keep it
                migrated_refs.append(ref)
                if verbose:
                    print(f"  {act_name}: '{ref}' (already slug)")

        migrated.append({**act, 'slides': migrated_refs})

    return migrated


def atomic_rename_all(slides_dir: Path, mapping: dict[str, str], verbose: bool = False) -> None:
    """Rename all directories atomically using two-phase approach.

    Phase 1: Rename all to temporary names (TEMP_{slug})
    Phase 2: Rename all to final names ({slug})

    This prevents conflicts when directories are interdependent.

    Args:
        slides_dir: Directory containing slides
        mapping: Dict of {old_dirname: new_slug}
        verbose: Print rename operations
    """
    if verbose:
        print("\n[Renaming Directories]")

    # Phase 1: All to temporary
    temp_mapping = {}
    for old_name, new_slug in mapping.items():
        old_path = slides_dir / old_name
        if not old_path.exists():
            continue  # Already renamed or doesn't exist

        temp_name = f"TEMP_{new_slug}"
        temp_path = slides_dir / temp_name

        if verbose:
            print(f"  Phase 1: {old_name} -> {temp_name}")

        old_path.rename(temp_path)
        temp_mapping[temp_name] = new_slug

    # Phase 2: Temporary to final
    for temp_name, final_slug in temp_mapping.items():
        temp_path = slides_dir / temp_name
        final_path = slides_dir / final_slug

        if verbose:
            print(f"  Phase 2: {temp_name} -> {final_slug}")

        temp_path.rename(final_path)

    if verbose:
        print(f"  ✓ {len(temp_mapping)} directories renamed")


def create_backup(presentation_path: Path, verbose: bool = False) -> tuple[Path, Path]:
    """Create backup of slides directory and config.

    Returns:
        Tuple of (backup_slides_dir, backup_config_path)
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    paths = get_presentation_output_paths(presentation_path)
    slides_dir = paths['slides_dir']
    config_path = presentation_path / 'outputs' / 'presentation' / 'config.yaml'

    backup_slides = slides_dir.parent / f"slides.backup-{timestamp}"
    backup_config = config_path.parent / f"config.yaml.backup-{timestamp}"

    if verbose:
        print("\n[Creating Backups]")
        print(f"  Slides: {backup_slides}")
        print(f"  Config: {backup_config}")

    shutil.copytree(slides_dir, backup_slides)
    if config_path.exists():
        shutil.copy2(config_path, backup_config)

    return backup_slides, backup_config


def rollback_migration(presentation_path: Path, backup_suffix: str, verbose: bool = False) -> None:
    """Restore from backup.

    Args:
        presentation_path: Path to presentation root
        backup_suffix: Timestamp suffix (e.g., "20260101_143022")
        verbose: Print rollback operations
    """
    if verbose:
        print(f"\n[Rolling Back from backup-{backup_suffix}]")

    paths = get_presentation_output_paths(presentation_path)
    slides_dir = paths['slides_dir']
    config_path = presentation_path / 'outputs' / 'presentation' / 'config.yaml'

    backup_slides = slides_dir.parent / f"slides.backup-{backup_suffix}"
    backup_config = config_path.parent / f"config.yaml.backup-{backup_suffix}"

    if not backup_slides.exists():
        raise MigrationError(f"Backup not found: {backup_slides}")

    # Remove current
    if slides_dir.exists():
        if verbose:
            print(f"  Removing current slides: {slides_dir}")
        shutil.rmtree(slides_dir)

    if config_path.exists():
        if verbose:
            print(f"  Removing current config: {config_path}")
        config_path.unlink()

    # Restore
    if verbose:
        print(f"  Restoring slides from: {backup_slides}")
    shutil.copytree(backup_slides, slides_dir)

    if backup_config.exists():
        if verbose:
            print(f"  Restoring config from: {backup_config}")
        shutil.copy2(backup_config, config_path)

    print(f"\n✓ Rollback complete")


def migrate_presentation(
    presentation_name: str,
    execute: bool = False,
    verbose: bool = False,
    keep_backup: bool = False,
) -> None:
    """Main migration orchestrator.

    Steps:
    1. Pre-flight checks
    2. Create backups (if execute)
    3. Generate slides list
    4. Migrate acts
    5. Rename directories (if execute)
    6. Update config
    7. Post-migration validation
    """
    presentation_path = get_presentation_path(presentation_name)
    paths = get_presentation_output_paths(presentation_path)
    slides_dir = paths['slides_dir']
    config_path = presentation_path / 'outputs' / 'presentation' / 'config.yaml'

    print(f"\nMigration Plan for '{presentation_name}'")
    print("=" * 60)

    # Step 1: Pre-flight checks
    check_result = preflight_checks(slides_dir, verbose=verbose)
    mapping = check_result['mapping']

    # Step 2: Generate slides list
    slides_list = generate_slides_list(slides_dir)

    print(f"\n[Generated Slides List] ({len(slides_list)} slides)")
    for i, slug in enumerate(slides_list, 1):
        print(f"  {i}. {slug}")

    # Step 3: Load and migrate config
    config = load_output_config(presentation_path, "presentation")

    # Check if already migrated
    if 'slides' in config and config['slides']:
        print("\n⚠️  WARNING: Presentation already has 'slides' list in config")
        print("  This presentation may have already been migrated.")
        if not execute:
            return

    # Migrate acts
    timing = config.get('timing', {})
    acts = timing.get('acts', [])

    if acts:
        try:
            migrated_acts = migrate_acts(acts, slides_list, verbose=verbose)
        except ValidationError as e:
            print(f"\n✗ Migration failed: {e}")
            return
    else:
        migrated_acts = []
        if verbose:
            print("\n[No acts to migrate]")

    # Step 4: Show directory renames
    print(f"\n[Directory Renames] ({len(mapping)} total)")
    for old_name, new_slug in list(mapping.items())[:10]:  # Show first 10
        if old_name != new_slug:
            print(f"  {old_name} -> {new_slug}")
        else:
            print(f"  {old_name} (no change)")
    if len(mapping) > 10:
        print(f"  ... and {len(mapping) - 10} more")

    # Step 5: Execute or dry-run
    if not execute:
        print("\n" + "=" * 60)
        print("DRY-RUN MODE - No changes made")
        print("Run with --execute to perform migration")
        return

    # Execute migration
    print("\n" + "=" * 60)
    print("EXECUTING MIGRATION")
    print("=" * 60)

    # Create backups
    backup_slides, backup_config = create_backup(presentation_path, verbose=verbose)
    backup_suffix = backup_slides.name.split('-')[-1]  # Extract timestamp

    try:
        # Rename directories
        atomic_rename_all(slides_dir, mapping, verbose=verbose)

        # Update config
        config['slides'] = slides_list
        if acts:
            config['timing']['acts'] = migrated_acts

        with config_path.open('w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False, width=80)

        if verbose:
            print(f"\n[Config Updated]")
            print(f"  Added 'slides' list with {len(slides_list)} entries")
            print(f"  Updated {len(acts)} acts with semantic slug references")

        # Verify
        print("\n[Post-Migration Validation]")
        new_dirs = list(slides_dir.iterdir())
        print(f"  ✓ {len(new_dirs)} directories present")

        # Check all expected slugs exist
        missing = [slug for slug in slides_list if not (slides_dir / slug).exists()]
        if missing:
            raise ValidationError(f"Missing slides after migration: {missing}")

        print(f"  ✓ All {len(slides_list)} slides found")
        print(f"  ✓ Config updated successfully")

        print("\n" + "=" * 60)
        print("✓ Migration completed successfully!")
        print("=" * 60)

        print(f"\nBackups created:")
        print(f"  Slides: {backup_slides}")
        print(f"  Config: {backup_config}")

        if not keep_backup:
            print(f"\nTo remove backups after verification:")
            print(f"  rm -rf {backup_slides}")
            print(f"  rm {backup_config}")

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        print(f"\nAttempting auto-rollback...")
        rollback_migration(presentation_path, backup_suffix, verbose=verbose)
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Migrate slide directories from numbered to semantic slugs"
    )
    parser.add_argument(
        '--presentation',
        type=str,
        help='Presentation name (default: active presentation)'
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Execute migration (default is dry-run)'
    )
    parser.add_argument(
        '--rollback',
        type=str,
        metavar='TIMESTAMP',
        help='Rollback from backup (provide timestamp like "20260101_143022")'
    )
    parser.add_argument(
        '--keep-backup',
        action='store_true',
        help='Keep backup after successful migration'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Detailed output'
    )

    args = parser.parse_args()

    # Get presentation
    presentation = args.presentation

    # Handle rollback
    if args.rollback:
        presentation_path = get_presentation_path(presentation)
        rollback_migration(presentation_path, args.rollback, verbose=args.verbose)
        return

    # Run migration
    try:
        migrate_presentation(
            presentation,
            execute=args.execute,
            verbose=args.verbose,
            keep_backup=args.keep_backup,
        )
    except MigrationError as e:
        print(f"\n✗ Error: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    exit(main())
