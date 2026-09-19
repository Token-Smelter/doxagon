"""The committed frontend build cannot drift from the source it serves.

``apps/web/backend/main.py`` mounts ``apps/web/frontend/build`` as the
production static root and that directory is committed, so a source fix that is
never rebuilt passes every source-level test while the hosted app keeps serving
the pre-fix bundle. ``npm run build`` writes a manifest of the digests of every
build input; this recomputes those digests from the same files and fails when
they disagree.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "apps" / "web" / "frontend"
BUILD = FRONTEND / "build"
MANIFEST = BUILD / ".doxagon-source-manifest.json"

# Mirrors `apps/web/frontend/scripts/stamp-build.mjs`; the manifest is a plain
# path -> digest map precisely so the two sides share no derivation to drift in.
INCLUDED_TREES = ("src", "static")
INCLUDED_FILES = ("package.json", "package-lock.json", "svelte.config.js", "vite.config.ts", "tsconfig.json")


def source_digests() -> dict[str, str]:
    paths: list[Path] = []
    for tree in INCLUDED_TREES:
        directory = FRONTEND / tree
        if directory.is_dir():
            # `is_file()` follows symlinks, so `static/presentation-runtime.js`
            # is read as the canonical runtime it links to: a runtime edit
            # invalidates the build that serves it.
            paths.extend(path for path in directory.rglob("*") if path.is_file())
    paths.extend(FRONTEND / name for name in INCLUDED_FILES if (FRONTEND / name).is_file())
    return {
        path.relative_to(FRONTEND).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def test_the_committed_build_was_produced_from_the_committed_source() -> None:
    if not BUILD.is_dir():
        pytest.skip("no committed frontend build in this checkout")
    assert MANIFEST.is_file(), (
        "the committed build carries no source manifest; run `npm run build` in apps/web/frontend "
        "so the served bundle records the source it came from"
    )

    recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))["sources"]
    observed = source_digests()

    changed = sorted(
        path for path in set(recorded) | set(observed) if recorded.get(path) != observed.get(path)
    )
    assert changed == [], (
        "apps/web/frontend/build is stale: "
        f"{len(changed)} build input(s) changed since it was produced ({', '.join(changed[:5])}). "
        "Run `npm run build` in apps/web/frontend and commit the regenerated build."
    )
