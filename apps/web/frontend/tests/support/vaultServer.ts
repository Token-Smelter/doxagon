import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { BrowserContext } from '@playwright/test';

/**
 * Run the production backend over a synthetic vault for a browser proof.
 *
 * `vault_server.py` serves `apps.web.backend.main.app` itself, so a test that
 * forwards the page's `/api` calls here exercises the real thesis list, the
 * real migrator, and the real Step workspace — not a stub of any of them.
 */

const SCRIPT = fileURLToPath(new URL('./vault_server.py', import.meta.url));
const REPO_ROOT = fileURLToPath(new URL('../../../../../', import.meta.url));
const PORT_LINE = 'PRESENTATION_VAULT_PORT=';
const START_TIMEOUT_MS = 120_000;

export interface VaultServer {
    /** Disposable filesystem root owned by this test server. */
    root: string;
    /** Origin of the running backend, e.g. `http://127.0.0.1:41234`. */
    base: string;
    stop(): Promise<void>;
}

/**
 * The interpreter that already holds this project's dependencies.
 *
 * The project virtualenv is preferred because the Python suite has just built
 * it; `uv run` is the fallback for a checkout where it does not exist yet.
 */
function interpreter(): { command: string; args: string[] } {
    const venv = join(REPO_ROOT, '.venv', 'bin', 'python');
    if (existsSync(venv)) return { command: venv, args: [] };
    return { command: 'uv', args: ['run', '--extra', 'dev', 'python'] };
}

export async function startVaultServer(): Promise<VaultServer> {
    const scratch = process.env.SOURCERER_SCRATCH_DIR ?? tmpdir();
    const root = mkdtempSync(join(scratch, 'presentation-vault-'));
    const { command, args } = interpreter();
    const child = spawn(command, [...args, SCRIPT, '--root', root], {
        cwd: REPO_ROOT,
        env: { ...process.env, PYTHONUNBUFFERED: '1' },
        stdio: ['ignore', 'pipe', 'pipe'],
    });

    const diagnostics: string[] = [];
    child.stderr.setEncoding('utf-8');
    child.stderr.on('data', (chunk: string) => diagnostics.push(chunk));

    const port = await readPort(child, diagnostics);
    const base = `http://127.0.0.1:${port}`;
    await waitUntilServing(base, diagnostics);

    return {
        root,
        base,
        async stop() {
            await stopChild(child);
            rmSync(root, { recursive: true, force: true });
        },
    };
}

function readPort(child: ChildProcess, diagnostics: string[]): Promise<number> {
    return new Promise((resolve, reject) => {
        let buffered = '';
        const fail = (reason: string) => reject(new Error(`${reason}\n${diagnostics.join('')}`));
        const timer = setTimeout(() => fail('the vault server never announced a port'), START_TIMEOUT_MS);
        child.stdout?.setEncoding('utf-8');
        child.stdout?.on('data', (chunk: string) => {
            buffered += chunk;
            const line = buffered.split('\n').find((item) => item.startsWith(PORT_LINE));
            if (line === undefined) return;
            clearTimeout(timer);
            resolve(Number(line.slice(PORT_LINE.length).trim()));
        });
        child.on('exit', (code) => {
            clearTimeout(timer);
            fail(`the vault server exited with code ${code} before serving`);
        });
        child.on('error', (error) => {
            clearTimeout(timer);
            fail(`the vault server could not be started: ${error.message}`);
        });
    });
}

async function waitUntilServing(base: string, diagnostics: string[]): Promise<void> {
    const deadline = Date.now() + START_TIMEOUT_MS;
    while (Date.now() < deadline) {
        try {
            const response = await fetch(`${base}/api/theses`);
            if (response.ok) return;
        } catch {
            // Not accepting yet; the bound socket is already listening, so this
            // only waits for uvicorn to finish starting.
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error(`the vault server never answered at ${base}\n${diagnostics.join('')}`);
}

function stopChild(child: ChildProcess): Promise<void> {
    if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve();
    return new Promise((resolve) => {
        child.once('exit', () => resolve());
        child.kill('SIGTERM');
        setTimeout(() => child.kill('SIGKILL'), 5_000).unref();
    });
}

/**
 * Send every `/api` call the context makes to the real backend.
 *
 * The route is registered on the context, not one page, so the presenter
 * window a Present click opens is served by the same producer as the editor
 * that opened it — which is the whole point of one shared session.
 *
 * `route.fetch` forwards the browser's own method, headers, and body and
 * returns the producer's own status, headers (the revision `ETag` included),
 * and body, so nothing between the editor and the vault is invented here.
 */
export async function useRealVault(context: BrowserContext, server: VaultServer): Promise<void> {
    await context.route('**/api/**', async (route) => {
        const url = new URL(route.request().url());
        try {
            const response = await route.fetch({ url: `${server.base}${url.pathname}${url.search}` });
            await route.fulfill({ response });
        } catch {
            // A promotion reloads the workspace while earlier reads are still in
            // flight, so a request the page has already abandoned can outlive
            // its own response. That is the page moving on, not the producer
            // failing, and forwarding a disposed response would fail the run
            // for a request nothing was waiting for.
            await route.abort('failed').catch(() => {});
        }
    });
}
