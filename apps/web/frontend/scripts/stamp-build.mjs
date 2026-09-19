/**
 * Stamp the committed frontend build with the digests of the source it came from.
 *
 * `apps/web/backend/main.py` mounts `apps/web/frontend/build` as the production
 * static root, and that directory is committed. A source fix that is never
 * rebuilt therefore passes every source-level test while the hosted app keeps
 * serving the pre-fix bundle. This manifest is written by `npm run build`, and
 * `tests/test_frontend_build_parity.py` recomputes it from the same files, so a
 * stale committed build fails the suite instead of shipping.
 */

import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const MANIFEST_KEY = '.doxagon-source-manifest.json';

/**
 * Everything a `vite build` of this app can read.
 *
 * `static/` is followed through symlinks on purpose: `presentation-runtime.js`
 * links to the canonical runtime, so a runtime edit must also invalidate the
 * build that serves it.
 */
const INCLUDED_TREES = ['src', 'static'];
const INCLUDED_FILES = ['package.json', 'package-lock.json', 'svelte.config.js', 'vite.config.ts', 'tsconfig.json'];

function walk(directory) {
    const found = [];
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
        const path = join(directory, entry.name);
        // statSync follows symlinks, so a linked file is read as a file.
        if (statSync(path).isDirectory()) found.push(...walk(path));
        else found.push(path);
    }
    return found;
}

/** Sorted `relative posix path -> sha256` over every build input. */
export function sourceDigests(root = ROOT) {
    const paths = [];
    for (const tree of INCLUDED_TREES) {
        const absolute = join(root, tree);
        try {
            if (statSync(absolute).isDirectory()) paths.push(...walk(absolute));
        } catch {
            // An absent optional tree contributes nothing rather than failing.
        }
    }
    for (const file of INCLUDED_FILES) {
        const absolute = join(root, file);
        try {
            if (statSync(absolute).isFile()) paths.push(absolute);
        } catch {
            // Same: absence is a fact the manifest records by omission.
        }
    }
    const digests = {};
    for (const path of paths.sort()) {
        digests[relative(root, path).split(/[\\/]/).join('/')] = createHash('sha256')
            .update(readFileSync(path))
            .digest('hex');
    }
    return digests;
}

const manifest = { schema: 'doxagon.frontend-build-source-manifest/1', sources: sourceDigests() };
writeFileSync(join(ROOT, 'build', MANIFEST_KEY), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
