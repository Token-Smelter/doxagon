#!/usr/bin/env python3
"""
Presentation Validation Utilities

Validates slide ordering consistency, act references, and compilation.

Usage:
    python factory/scripts/validate_presentation.py --presentation sample-editorial
    python factory/scripts/validate_presentation.py --check-ordering
    python factory/scripts/validate_presentation.py --check-acts
    python factory/scripts/validate_presentation.py --check-compile
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from utils import (
    get_presentation_path,
    get_presentation_output_paths,
    load_output_config,
    get_slide_order,
    find_slide_dir,
    natural_sort_key,
    normalize_slug,
)


class ValidationResult(NamedTuple):
    """Result of a validation check."""
    passed: bool
    message: str
    details: dict | None = None


def validate_slide_ordering(presentation_path: Path, verbose: bool = False) -> ValidationResult:
    """
    Validate slide ordering consistency.

    Checks:
    - Config has 'slides' list
    - All slides in config exist on disk
    - All slides on disk are in config
    - Config order matches intended presentation flow

    Returns:
        ValidationResult with ordering status
    """
    paths = get_presentation_output_paths(presentation_path)
    slides_dir = paths['slides_dir']

    config = load_output_config(presentation_path, "presentation")
    config_slides = config.get('slides', [])

    # Check 1: Config has slides list
    if not config_slides:
        return ValidationResult(
            passed=False,
            message="Config missing 'slides' list - presentation not migrated",
            details={'config_path': presentation_path / 'outputs' / 'presentation' / 'config.yaml'}
        )

    # Check 2: All config slides exist on disk
    missing_slides = []
    for slug in config_slides:
        slide_dir = find_slide_dir(slides_dir, slug)
        if not slide_dir:
            missing_slides.append(slug)

    if missing_slides:
        return ValidationResult(
            passed=False,
            message=f"Config references {len(missing_slides)} missing slides",
            details={'missing_slides': missing_slides}
        )

    # Check 3: All disk slides are in config
    disk_dirs = [d for d in slides_dir.iterdir() if d.is_dir()]
    disk_slugs = [normalize_slug(d.name) for d in disk_dirs]
    extra_slides = [slug for slug in disk_slugs if slug not in config_slides]

    if extra_slides:
        return ValidationResult(
            passed=False,
            message=f"{len(extra_slides)} slides on disk not in config",
            details={'extra_slides': extra_slides}
        )

    # Check 4: Order consistency (informational)
    details = {
        'config_order': config_slides,
        'total_slides': len(config_slides),
        'all_slides_found': True
    }

    if verbose:
        details['slide_mapping'] = {
            slug: find_slide_dir(slides_dir, slug).name
            for slug in config_slides
        }

    return ValidationResult(
        passed=True,
        message=f"Slide ordering valid: {len(config_slides)} slides in config, all found on disk",
        details=details
    )


def validate_acts_references(presentation_path: Path, verbose: bool = False) -> ValidationResult:
    """
    Validate all act slide references exist.

    Checks:
    - All slides referenced in acts exist in config
    - All slides referenced in acts exist on disk
    - No orphaned act references

    Returns:
        ValidationResult with acts validation status
    """
    paths = get_presentation_output_paths(presentation_path)
    slides_dir = paths['slides_dir']

    config = load_output_config(presentation_path, "presentation")
    config_slides = config.get('slides', [])

    if not config_slides:
        return ValidationResult(
            passed=False,
            message="Cannot validate acts - config missing 'slides' list",
            details=None
        )

    timing = config.get('timing', {})
    acts = timing.get('acts', [])

    if not acts:
        return ValidationResult(
            passed=True,
            message="No acts defined - validation skipped",
            details={'acts_count': 0}
        )

    # Collect all act references
    invalid_refs = []
    valid_refs = []

    for act in acts:
        act_name = act.get('name', 'Unnamed')
        slide_refs = act.get('slides', [])

        for ref in slide_refs:
            # Check if ref exists in config
            if ref not in config_slides:
                invalid_refs.append({
                    'act': act_name,
                    'slide': ref,
                    'reason': 'not in config'
                })
                continue

            # Check if ref exists on disk
            slide_dir = find_slide_dir(slides_dir, ref)
            if not slide_dir:
                invalid_refs.append({
                    'act': act_name,
                    'slide': ref,
                    'reason': 'not found on disk'
                })
                continue

            valid_refs.append({'act': act_name, 'slide': ref})

    if invalid_refs:
        return ValidationResult(
            passed=False,
            message=f"{len(invalid_refs)} invalid act references found",
            details={
                'invalid_refs': invalid_refs,
                'valid_refs_count': len(valid_refs)
            }
        )

    return ValidationResult(
        passed=True,
        message=f"All act references valid: {len(valid_refs)} references across {len(acts)} acts",
        details={
            'acts_count': len(acts),
            'total_refs': len(valid_refs),
            'refs_by_act': {
                act['name']: len(act.get('slides', []))
                for act in acts
            }
        }
    )


def validate_compilation(presentation_path: Path, verbose: bool = False) -> ValidationResult:
    """
    Test that presentation compiles successfully.

    Runs compile.py with --no-pptx flag to avoid dependency issues.

    Returns:
        ValidationResult with compilation status
    """
    try:
        # Run compile.py
        cmd = [
            'python3',
            'factory/scripts/compile.py',
            '--presentation', presentation_path.name,
            '--no-pptx'
        ]

        if verbose:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
        else:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

        if result.returncode == 0:
            # Extract slide count from output
            output = result.stdout
            slide_count = None
            for line in output.split('\n'):
                if line.startswith('Total slides:'):
                    slide_count = int(line.split(':')[1].strip())

            return ValidationResult(
                passed=True,
                message=f"Compilation successful: {slide_count} slides compiled",
                details={
                    'slide_count': slide_count,
                    'output': output if verbose else None
                }
            )
        else:
            return ValidationResult(
                passed=False,
                message="Compilation failed",
                details={
                    'stdout': result.stdout,
                    'stderr': result.stderr,
                    'returncode': result.returncode
                }
            )

    except subprocess.TimeoutExpired:
        return ValidationResult(
            passed=False,
            message="Compilation timeout (30s exceeded)",
            details=None
        )
    except Exception as e:
        return ValidationResult(
            passed=False,
            message=f"Compilation error: {e}",
            details=None
        )


def main():
    parser = argparse.ArgumentParser(
        description="Validate presentation structure and configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--presentation',
        type=str,
        help='Presentation name (default: active presentation)'
    )
    parser.add_argument(
        '--check-ordering',
        action='store_true',
        help='Validate slide ordering consistency'
    )
    parser.add_argument(
        '--check-acts',
        action='store_true',
        help='Validate act references'
    )
    parser.add_argument(
        '--check-compile',
        action='store_true',
        help='Test compilation'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Detailed output'
    )

    args = parser.parse_args()

    # Determine presentation
    presentation = args.presentation
    if not presentation:
        print("Error: No presentation specified")
        print("Use --presentation NAME")
        sys.exit(1)

    presentation_path = get_presentation_path(presentation)
    if not presentation_path.exists():
        print(f"Error: Presentation not found: {presentation_path}")
        sys.exit(1)

    # Determine what to check
    check_all = not (args.check_ordering or args.check_acts or args.check_compile)

    print(f"Validating presentation '{presentation}'")
    print("=" * 60)

    results = []

    # Check ordering
    if check_all or args.check_ordering:
        print("\n[Slide Ordering]")
        result = validate_slide_ordering(presentation_path, verbose=args.verbose)
        results.append(('Ordering', result))

        status = "✓" if result.passed else "✗"
        print(f"{status} {result.message}")

        if args.verbose and result.details:
            for key, value in result.details.items():
                if isinstance(value, list):
                    print(f"  {key}: {len(value)} items")
                    for item in value[:5]:  # Show first 5
                        print(f"    - {item}")
                    if len(value) > 5:
                        print(f"    ... and {len(value) - 5} more")
                else:
                    print(f"  {key}: {value}")

    # Check acts
    if check_all or args.check_acts:
        print("\n[Act References]")
        result = validate_acts_references(presentation_path, verbose=args.verbose)
        results.append(('Acts', result))

        status = "✓" if result.passed else "✗"
        print(f"{status} {result.message}")

        if args.verbose and result.details:
            for key, value in result.details.items():
                if key == 'refs_by_act':
                    print(f"  {key}:")
                    for act, count in value.items():
                        print(f"    {act}: {count} slides")
                elif isinstance(value, list):
                    print(f"  {key}: {len(value)} items")
                else:
                    print(f"  {key}: {value}")

    # Check compilation
    if check_all or args.check_compile:
        print("\n[Compilation]")
        result = validate_compilation(presentation_path, verbose=args.verbose)
        results.append(('Compilation', result))

        status = "✓" if result.passed else "✗"
        print(f"{status} {result.message}")

        if not result.passed and result.details:
            if result.details.get('stderr'):
                print("\nError output:")
                print(result.details['stderr'])

    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for _, r in results if r.passed)
    total = len(results)

    if passed == total:
        print(f"✓ All {total} validation checks passed")
        return 0
    else:
        print(f"✗ {passed}/{total} validation checks passed")
        return 1


if __name__ == '__main__':
    exit(main())
