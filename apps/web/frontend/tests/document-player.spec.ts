import { expect, test, type Frame, type Page } from '@playwright/test';
import { mkdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import type { DocumentPosition } from '../src/lib/presentation/documentBridge';

const FIXTURES = fileURLToPath(new URL('../../../../tests/fixtures/documents/', import.meta.url));
const html = readFileSync(join(FIXTURES, 'observatory.html'));
const notes = readFileSync(join(FIXTURES, 'observatory.notes.json'));

async function waitForDocumentInput(page: Page) {
    await expect(page.getByLabel('Open local HTML')).toHaveAttribute('data-ready', 'true');
}

async function openDocument(page: Page, name = 'observatory.html') {
    await page.goto('/presentations/document');
    await waitForDocumentInput(page);
    await page.getByLabel('Open local HTML').setInputFiles(join(FIXTURES, name));
    await expect(page.getByTestId('document-cue')).toHaveText(name === 'tide.html' ? '1 / 2' : '1 / 5');
    return page.frames().find((frame) => frame.url().startsWith('blob:'))!;
}
const state = (frame: Frame) => frame.evaluate<DocumentPosition>('window.observatory.state()');
const instance = (frame: Frame) => frame.evaluate<string>('window.observatory.instance');

async function evidence(page: Page, name: string) {
    const root = process.env.DOXAGON_DOCUMENT_EVIDENCE;
    if (!root) return;
    mkdirSync(root, { recursive: true });
    await page.screenshot({ path: join(root, name), fullPage: false });
}

for (const nativeHash of [true, false]) {
    test(`normal Present loads notes and navigation ${nativeHash ? 'with' : 'without'} Web Crypto`, async ({ page }) => {
    if (!nativeHash) {
        await page.addInitScript(() => Object.defineProperty(window.crypto, 'subtle', { value: undefined, configurable: true }));
    }
    const base = '/api/theses/observatory/authored-document';
    const checkpointReads: string[] = [];
    await page.route('**/api/presentations/**', route => { checkpointReads.push(route.request().url()); return route.abort(); });
    await page.route(`**${base}`, route => route.fulfill({ json: {
        filename: 'observatory.html', url: `${base}/html`, notesUrl: `${base}/notes`,
        sha256: createHash('sha256').update(html).digest('hex'),
    } }));
    await page.route(`**${base}/html`, route => route.fulfill({ body: html, contentType: 'application/octet-stream' }));
    await page.route(`**${base}/notes?document_sha256=*`, route => route.fulfill({ body: notes, contentType: 'application/octet-stream' }));
    await page.goto('/present/observatory');
    await expect(page.getByTestId('document-cue')).toHaveText('1 / 5');
    await expect(page.getByLabel('Open local HTML')).toHaveCount(0);
    const frame = page.frames().find(frame => frame.url().startsWith('blob:'))!;
    const loaded = await instance(frame);
    const popupPromise = page.waitForEvent('popup');
    await page.getByRole('button', { name: 'Speaker notes', exact: true }).click();
    const popup = await popupPromise;
    await expect(popup.getByTestId('speaker-note')).toHaveText('Introduce the synthetic observatory.');
    await popup.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(page.getByTestId('document-cue')).toHaveText('2 / 5');
    expect({ checkpointReads, loaded: await instance(frame) }).toEqual({ checkpointReads: [], loaded });
    });
}

test('URL playback uses the pinned frame and keeps notes private without downloading HTML into the host', async ({ page }) => {
    const base = '/api/theses/observatory/authored-document';
    const digest = createHash('sha256').update(html).digest('hex');
    const renderUrl = `${base}/render/${digest}`;
    const byteDownloads: string[] = [];
    await page.route(`**${base}`, route => route.fulfill({ json: {
        filename: 'observatory.html', url: `${base}/html`, renderUrl, notesUrl: `${base}/notes`, sha256: digest,
    } }));
    await page.route(`**${base}/html`, route => { byteDownloads.push(route.request().url()); return route.abort(); });
    await page.route(`**${renderUrl}`, route => route.fulfill({ body: html, contentType: 'text/html', headers: {
        'Content-Security-Policy': "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; frame-ancestors 'self'",
    } }));
    await page.route(`**${base}/notes?document_sha256=*`, route => route.fulfill({ body: notes, contentType: 'application/octet-stream' }));
    await page.goto('/present/observatory');
    await expect(page.getByTestId('document-cue')).toHaveText('1 / 5');
    const frame = page.frames().find(frame => frame.url().endsWith(renderUrl))!;
    const loaded = await instance(frame);
    const popupPromise = page.waitForEvent('popup');
    await page.getByRole('button', { name: 'Present', exact: true }).click();
    const popup = await popupPromise;
    await expect(popup.getByTestId('speaker-note')).toHaveText('Introduce the synthetic observatory.');
    await popup.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(page.getByTestId('document-cue')).toHaveText('2 / 5');
    expect(await frame.content()).not.toContain('Introduce the synthetic observatory.');
    await popup.getByRole('button', { name: 'End presentation', exact: true }).click();
    await page.getByRole('button', { name: 'Reconnect', exact: true }).click();
    await expect(page.getByTestId('document-cue')).toHaveText('2 / 5');
    expect({ byteDownloads, instance: await instance(frame) }).toEqual({ byteDownloads: [], instance: loaded });
});

test('an early bridge invitation does not get reset when the URL frame finishes loading', async ({ page }) => {
    const base = '/api/theses/observatory/authored-document';
    const early = Buffer.concat([html, Buffer.from("<script>parent.postMessage({type:'doxagon:available'}, '*')</script>")]);
    const sha256 = createHash('sha256').update(early).digest('hex');
    const renderUrl = `${base}/render/${sha256}`;
    await page.route(`**${base}`, route => route.fulfill({ json: {
        filename: 'observatory.html', url: `${base}/html`, renderUrl, notesUrl: null, sha256,
    } }));
    await page.route(`**${renderUrl}`, route => route.fulfill({ body: early, contentType: 'text/html' }));
    await page.goto('/present/observatory');
    await expect(page.getByTestId('document-cue')).toHaveText('1 / 5');
    const frame = page.frames().find(frame => frame.url().endsWith(renderUrl))!;
    const loaded = await instance(frame);
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(page.getByTestId('document-cue')).toHaveText('2 / 5');
    await frame.evaluate("parent.postMessage({type:'doxagon:available'}, '*')");
    await page.waitForTimeout(100);
    expect(await instance(frame)).toBe(loaded);
    await expect(page.getByTestId('document-cue')).toHaveText('2 / 5');
});

test('a selected render URL cannot point outside its hash-pinned thesis endpoint', async ({ page }) => {
    const base = '/api/theses/observatory/authored-document';
    await page.route(`**${base}`, route => route.fulfill({ json: {
        filename: 'observatory.html', url: `${base}/html`, renderUrl: '/untrusted.html', notesUrl: null,
        sha256: createHash('sha256').update(html).digest('hex'),
    } }));
    await page.goto('/present/observatory');
    await expect(page.getByTestId('presenter-failure')).toContainText('invalid authored document selection');
    await expect(page.locator('iframe')).toHaveCount(0);
});

test('local file playback hashes the full document without Web Crypto', async ({ page }) => {
    await page.addInitScript(() => Object.defineProperty(window.crypto, 'subtle', { value: undefined, configurable: true }));
    const frame = await openDocument(page);
    await page.getByText('File identity', { exact: true }).click();
    await expect(page.locator('details')).toContainText(createHash('sha256').update(html).digest('hex'));
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(page.getByTestId('document-cue')).toHaveText('2 / 5');
    expect((await state(frame)).index).toBe(1);
});

test('without Web Crypto a saved hash mismatch is rejected and can be retried', async ({ page }) => {
    await page.addInitScript(() => Object.defineProperty(window.crypto, 'subtle', { value: undefined, configurable: true }));
    const base = '/api/theses/observatory/authored-document';
    const changed = Buffer.concat([html, Buffer.from('<!-- changed -->')]);
    await page.route(`**${base}`, route => route.fulfill({ json: {
        filename: 'observatory.html', url: `${base}/html`, notesUrl: null,
        sha256: createHash('sha256').update(html).digest('hex'),
    } }));
    await page.route(`**${base}/html`, route => route.fulfill({ body: changed, contentType: 'application/octet-stream' }));
    await page.goto('/present/observatory');
    await expect(page.getByRole('alert')).toContainText('changed while opening');
    await expect(page.getByRole('heading', { name: 'Could not open the saved presentation' })).toBeVisible();
    await expect(page.getByText('One document. Uninterrupted.', { exact: true })).toHaveCount(0);
    await expect(page.locator('iframe')).toHaveCount(0);
    await page.unroute(`**${base}/html`);
    await page.route(`**${base}/html`, route => route.fulfill({ body: html, contentType: 'application/octet-stream' }));
    await page.getByRole('button', { name: 'Retry opening', exact: true }).click();
    await expect(page.getByTestId('document-cue')).toHaveText('1 / 5');
});

test('direct playback retains the authored frame through a blocked notes popup and recovery', async ({ page }) => {
    await page.addInitScript(() => Object.defineProperty(window.crypto, 'subtle', { value: undefined, configurable: true }));
    const base = '/api/theses/observatory/authored-document';
    const checkpointReads: string[] = [];
    await page.route('**/api/theses', route => route.fulfill({ json: [{ slug: 'observatory', name: 'Observatory', title: 'Observatory', slide_count: 5 }] }));
    await page.route('**/api/presentations/**', route => { checkpointReads.push(route.request().url()); return route.abort(); });
    await page.route(`**${base}`, route => route.fulfill({ json: {
        filename: 'observatory.html', url: `${base}/html`, notesUrl: `${base}/notes`,
        sha256: createHash('sha256').update(html).digest('hex'),
    } }));
    await page.route(`**${base}/html`, route => route.fulfill({ body: html, contentType: 'application/octet-stream' }));
    await page.route(`**${base}/notes?document_sha256=*`, route => route.fulfill({ body: notes, contentType: 'application/octet-stream' }));
    await page.goto('/present/observatory');
    await expect(page.getByTestId('document-cue')).toHaveText('1 / 5');
    const frame = page.frames().find(frame => frame.url().startsWith('blob:'))!;
    const loaded = await instance(frame);
    await page.evaluate('window.savedOpen = window.open; window.open = () => null');
    await page.getByRole('button', { name: 'Present', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('Allow pop-ups');
    await page.evaluate('window.open = window.savedOpen');
    const popupPromise = page.waitForEvent('popup');
    await page.getByRole('button', { name: 'Open speaker notes', exact: true }).click();
    const popup = await popupPromise;
    await expect(page.getByTestId('authored-audience')).toBeVisible();
    await expect(popup.getByTestId('speaker-note')).toHaveText('Introduce the synthetic observatory.');
    await popup.getByRole('button', { name: 'Next', exact: true }).click();
    await expect.poll(async () => (await state(frame)).index).toBe(1);
    await expect(popup.getByTestId('speaker-note')).toContainText('Measure one orbit.');
    expect(await instance(frame)).toBe(loaded);
    await popup.getByRole('button', { name: 'End presentation', exact: true }).click();
    await expect(page.getByTestId('authored-player')).toBeVisible();
    expect({ checkpointReads, loaded: await instance(frame), closed: popup.isClosed() }).toEqual({ checkpointReads: [], loaded, closed: true });
});

test('a broken authored selection reports the problem instead of reviving the legacy player', async ({ page }) => {
    const checkpointReads: string[] = [];
    await page.route('**/api/presentations/**', route => { checkpointReads.push(route.request().url()); return route.abort(); });
    await page.route('**/api/theses/broken/authored-document', route => route.fulfill({ status: 422, json: { detail: 'Selected file missing' } }));
    await page.goto('/present/broken');
    await expect(page.getByTestId('presenter-failure')).toContainText('selected authored document');
    expect(checkpointReads).toEqual([]);
});

test('the presentation UI opens two explicitly selected documents without upload or conversion', async ({ page }) => {
    const writes: string[] = [];
    page.on('request', (request) => { if (request.method() !== 'GET') writes.push(request.url()); });
    await page.route('**/api/theses', route => route.fulfill({ json: [] }));
    await page.goto('/presentations');
    await page.getByRole('button', { name: 'Toggle presentations sidebar', exact: true }).click();
    await page.getByRole('link', { name: 'Open HTML document', exact: true }).click();
    await waitForDocumentInput(page);
    await page.getByLabel('Open local HTML').setInputFiles(join(FIXTURES, 'observatory.html'));
    await expect(page.getByTestId('document-cue')).toHaveText('1 / 5');
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(page.getByTestId('document-cue')).toHaveText('2 / 5');
    await waitForDocumentInput(page);
    await page.getByLabel('Open local HTML').setInputFiles(join(FIXTURES, 'tide.html'));
    await expect(page.getByTestId('document-cue')).toHaveText('1 / 2');
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(page.getByTestId('document-cue')).toHaveText('2 / 2');
    expect(page.frames().filter((frame) => frame.url().startsWith('blob:'))).toHaveLength(1);
    expect(writes).toEqual([]);
});

test('adjacent travel preserves intermediate visuals and frame identity; distant jumps snap', async ({ page }) => {
    const frame = await openDocument(page);
    const loaded = await instance(frame);
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect.poll(async () => (await state(frame)).progress).toBeGreaterThan(0.05);
    const intermediate = await state(frame);
    expect(intermediate.index).toBe(0);
    expect(intermediate.progress).toBeLessThan(1);
    const partial = await frame.locator('#orbit').evaluate((node) => getComputedStyle(node).transform);
    await expect(page.getByTestId('document-cue')).toHaveText('2 / 5');
    expect(await frame.locator('#orbit').evaluate((node) => getComputedStyle(node).transform)).not.toBe(partial);
    await page.getByRole('button', { name: 'Back', exact: true }).click();
    await expect(page.getByTestId('document-cue')).toHaveText('1 / 5');
    await page.getByLabel('Jump to cue').selectOption('cue-4');
    await expect(page.getByTestId('document-cue')).toHaveText('5 / 5');
    expect(await instance(frame)).toBe(loaded);
    expect(await frame.evaluate('window.observatory.commands.map(command => command.type)')).toEqual(['next', 'previous', 'go']);
    await evidence(page, 'document-player-desktop.png');
});

test('keyboard focus belongs to its window and native controls do not double navigate', async ({ page }) => {
    const frame = await openDocument(page);
    await page.getByRole('heading', { name: 'Document player', exact: true }).click();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByTestId('document-cue')).toHaveText('2 / 5');
    await page.getByRole('button', { name: 'Next', exact: true }).focus();
    await page.keyboard.press('Space');
    await expect(page.getByTestId('document-cue')).toHaveText('3 / 5');
    expect(await frame.evaluate('window.observatory.commands.length')).toBe(2);
    await page.getByLabel('Open local HTML').focus();
    await page.keyboard.press('ArrowRight');
    expect(await frame.evaluate('window.observatory.commands.length')).toBe(2);
    await frame.locator('h1').click();
    await page.keyboard.press('ArrowLeft');
    await expect(page.getByTestId('document-cue')).toHaveText('2 / 5');
    expect(await frame.evaluate('window.observatory.commands.length')).toBe(2);
});

test('manual wheel input interrupts animated travel without a host feedback seek', async ({ page }) => {
    const frame = await openDocument(page);
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect.poll(async () => (await state(frame)).progress).toBeGreaterThan(0.1);
    await page.locator('iframe').hover();
    await page.mouse.wheel(0, -40);
    await page.waitForTimeout(150);
    const stopped = await frame.evaluate('scrollY');
    await page.waitForTimeout(1000);
    expect(await frame.evaluate('scrollY')).toBe(stopped);
    expect((await state(frame)).progress).toBeLessThan(0.9);
    expect(await frame.evaluate('window.observatory.commands.length')).toBe(1);
});

test('reduced motion and a narrow viewport retain usable document controls', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const frame = await openDocument(page);
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(page.getByTestId('document-cue')).toHaveText('2 / 5');
    expect((await state(frame)).progress).toBe(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await evidence(page, 'document-player-mobile.png');
});

test('private notes validate identity, follow scrolling, and drive the same document', async ({ page }) => {
    const frame = await openDocument(page);
    const loaded = await instance(frame);
    const popupPromise = page.waitForEvent('popup');
    await page.getByRole('button', { name: 'Speaker notes', exact: true }).click();
    const popup = await popupPromise;
    await expect(popup.getByTestId('speaker-note')).toContainText('Choose the companion');
    const mismatch = JSON.parse(notes.toString());
    for (const key of ['documentId', 'edition']) {
        await popup.getByLabel('Choose companion notes').setInputFiles({ name: 'wrong.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ ...mismatch, [key]: 'wrong' })) });
        await expect(popup.getByRole('alert')).toContainText('do not match');
    }
    await popup.getByLabel('Choose companion notes').setInputFiles(join(FIXTURES, 'observatory.notes.json'));
    await expect(popup.getByTestId('speaker-note')).toHaveText('Introduce the synthetic observatory.');
    await popup.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(page.getByTestId('document-cue')).toHaveText('2 / 5');
    await expect(popup.getByTestId('speaker-note')).toContainText('<img src=x onerror=alert(1)>');
    await expect(popup.locator('img')).toHaveCount(0);
    await frame.evaluate('scrollTo(0, innerHeight * 2.4)');
    await expect(popup.getByTestId('speaker-note')).toHaveText('Compare two measurements.');
    await popup.getByLabel('Jump to cue').selectOption('cue-4');
    await expect(page.getByTestId('document-cue')).toHaveText('5 / 5');
    expect(await instance(frame)).toBe(loaded);
    expect(await popup.evaluate(() => window.opener)).toBeNull();
    expect(await page.content()).not.toContain('Introduce the synthetic observatory.');
    expect(await frame.content()).not.toContain('Introduce the synthetic observatory.');
    expect(await popup.locator('header').evaluate((node) => getComputedStyle(node).backgroundColor)).toBe('rgb(22, 19, 15)');
    await evidence(popup, 'document-notes.png');
    await page.getByRole('link', { name: 'Back to presentations', exact: true }).click();
    await expect.poll(() => popup.isClosed()).toBe(true);
});

for (const action of ['reload', 'close'] as const) {
    test(`private notes close when the owning browser tab ${action}s`, async ({ page }) => {
        await openDocument(page);
        const popupPromise = page.waitForEvent('popup');
        await page.getByRole('button', { name: 'Speaker notes', exact: true }).click();
        const popup = await popupPromise;
        await popup.getByLabel('Choose companion notes').setInputFiles(join(FIXTURES, 'observatory.notes.json'));
        await expect(popup.getByTestId('speaker-note')).toHaveText('Introduce the synthetic observatory.');
        if (action === 'reload') await page.reload();
        else await page.close({ runBeforeUnload: true });
        await expect.poll(() => popup.isClosed()).toBe(true);
    });
}

test('popup blocking has an actionable retry and closing notes permits reopening', async ({ page }) => {
    await openDocument(page);
    await page.evaluate('window.savedOpen = window.open; window.open = () => null');
    await page.getByRole('button', { name: 'Speaker notes', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('Allow pop-ups');
    await page.evaluate('window.open = window.savedOpen');
    for (let i = 0; i < 2; i++) {
        const popupPromise = page.waitForEvent('popup');
        await page.getByRole('button', { name: 'Speaker notes', exact: true }).click();
        const popup = await popupPromise;
        await expect(popup.getByTestId('speaker-note')).toContainText('Choose the companion');
        await popup.close();
    }
});

test('malformed and mismatched port positions fail closed and reconnect retains the loaded frame', async ({ page }) => {
    const frame = await openDocument(page);
    const loaded = await instance(frame);
    const valid = await state(frame);
    for (const bad of [null, [], { ...valid, documentId: 'foreign' }, { ...valid, edition: 'old' }, { ...valid, cue: 'unknown' }, { ...valid, index: 1 }, { ...valid, total: 7 }, { ...valid, progress: 1.1 }, { ...valid, progress: '0.5' }, { ...valid, type: 'ready' }]) {
        await frame.evaluate((value) => (window as any).observatory.send(value), bad);
        await expect(page.getByRole('alert')).toContainText('invalid position');
        await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled();
        await page.getByRole('button', { name: 'Reconnect', exact: true }).click();
        await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeEnabled();
    }
    expect(await instance(frame)).toBe(loaded);
});

test('stale ports and window messages cannot move a reconnected document session', async ({ page }) => {
    const frame = await openDocument(page);
    await frame.evaluate('window.retiredPort = window.observatory.oldPort()');
    await page.getByRole('button', { name: 'Reconnect', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeEnabled();
    await frame.evaluate(`window.retiredPort.postMessage({ ...window.observatory.state(), edition: 'retired' }); top.postMessage({ ...window.observatory.state(), cue: 'cue-4', index: 4 }, '*')`);
    await page.waitForTimeout(100);
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expect(page.getByTestId('document-cue')).toHaveText('1 / 5');
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(page.getByTestId('document-cue')).toHaveText('2 / 5');
});

test('the document cannot read app state, open popups or use ambient network', async ({ page }) => {
    const frame = await openDocument(page);
    const result = await frame.evaluate(async () => {
        let parentRead = false;
        let topRead = false;
        let storage = false;
        let network = false;
        try { parentRead = Boolean(parent.document.body); } catch { /* expected sandbox denial */ }
        try { topRead = Boolean(top!.document.body); } catch { /* expected sandbox denial */ }
        try { localStorage.setItem('probe', '1'); storage = true; } catch { /* expected sandbox denial */ }
        try { await fetch('/api/theses'); network = true; } catch { /* expected CSP denial */ }
        const popup = window.open('about:blank');
        return { parentRead, topRead, storage, network, popup: popup !== null };
    });
    expect(result).toEqual({ parentRead: false, topRead: false, storage: false, network: false, popup: false });
    await expect(page.locator('iframe')).toHaveAttribute('sandbox', 'allow-scripts');
});

test('reconnect refuses a new document identity on the same loaded frame', async ({ page }) => {
    const frame = await openDocument(page);
    await frame.evaluate(`window.savedPost = MessagePort.prototype.postMessage;
        MessagePort.prototype.postMessage = function (message, ...args) {
            return window.savedPost.call(this, message?.type === 'ready' ? { ...message, edition: 'swapped' } : message, ...args);
        };`);
    await page.getByRole('button', { name: 'Reconnect', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('mismatched bridge handshake');
    await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled();
    await frame.evaluate('MessagePort.prototype.postMessage = window.savedPost');
    await page.getByRole('button', { name: 'Reconnect', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeEnabled();
});

test('a malformed ready handshake is refused rather than enabling controls', async ({ page }) => {
    await page.goto('/presentations/document');
    const bad = html.toString().replace("port.postMessage({ type: 'ready', documentId, edition, cues });", "port.postMessage({ type: 'ready', documentId, edition, cues: [{ id: 'x', title: 'one' }, { id: 'x', title: 'duplicate' }] });");
    await waitForDocumentInput(page);
    await page.getByLabel('Open local HTML').setInputFiles({ name: 'bad.html', mimeType: 'text/html', buffer: Buffer.from(bad) });
    await expect(page.getByRole('alert')).toContainText('invalid or mismatched bridge handshake');
    await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled();
});

test('unsupported HTML reports a recovery instead of waiting forever', async ({ page }) => {
    await page.goto('/presentations/document');
    await waitForDocumentInput(page);
    await page.getByLabel('Open local HTML').setInputFiles({ name: 'plain.html', mimeType: 'text/html', buffer: Buffer.from('<!doctype html><title>Plain</title><p>No bridge here.</p>') });
    await expect(page.getByRole('alert')).toContainText('No compatible document bridge');
    await waitForDocumentInput(page);
    await page.getByLabel('Open local HTML').setInputFiles(join(FIXTURES, 'observatory.html'));
    await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeEnabled();
});
