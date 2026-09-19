import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const document = readFileSync(fileURLToPath(new URL(
    '../../../../tests/fixtures/presentations/scene-deck.offline.html', import.meta.url,
)), 'utf8');

async function openScene(page: Page) {
    await page.setContent(document, { waitUntil: 'load' });
    await expect.poll(() => page.evaluate(() => window.document.documentElement.dataset.doxagonReady)).toBe('true');
}

const inspect = (page: Page) => page.evaluate(() => window.doxagonDeck.runtime.inspect());
const state = (page: Page) => page.evaluate(() => window.doxagonDeck.state());
const seek = (page: Page, id: string) => page.evaluate((id) => window.doxagonDeck.seek(id), id);
const next = (page: Page) => page.evaluate(() => window.doxagonDeck.dispatch({ type: 'NEXT' }));

async function issue(page: Page, sequence: number, checkpoint: string, type = 'NEXT', from = 'shape-start', epoch = 0) {
    return page.evaluate(({ sequence, checkpoint, type, from, epoch }) => window.doxagonDeck.runtime.adopt({
        schema: 'doxagon.presentation-snapshot/2', session_id: 'test-session', deck_revision: window.doxagonDeck.revision,
        epoch, sequence, checkpoint_id: checkpoint, issued_at: '2026-09-05T00:00:00Z',
        navigation: { type: type as 'NEXT', from },
    }), { sequence, checkpoint, type, from, epoch });
}

test('Next moves the same SVG and image while the scene simulation stays alive', async ({ page }) => {
    await openScene(page);
    const frame = await page.locator('#doxagon-stage iframe').elementHandle();
    const before = await inspect(page);
    const moving = next(page);
    await expect.poll(async () => (await inspect(page))?.transitions).toBe(1);
    const mid = await inspect(page);
    expect((await state(page)).checkpointId).toBe('shape-start');
    await moving;
    expect(await frame!.evaluate((frame) => frame.isConnected)).toBe(true);
    expect(await inspect(page)).toMatchObject({ current: 'shape-moved', contextId: 'shape-moved', transitions: 1, position: [150, 40] });
    expect((await inspect(page))!.ticks).toBeGreaterThan(before!.ticks as number);
    expect(mid!.direction).toBe('forward');
    await expect(page.frameLocator('#doxagon-stage iframe').locator('image')).toHaveAttribute('x', '195');
});

test('Back uses separately authored motion without replacing the scene', async ({ page }) => {
    await openScene(page);
    await next(page);
    const back = page.evaluate(() => window.doxagonDeck.dispatch({ type: 'PREVIOUS' }));
    await expect.poll(async () => ((await inspect(page))?.position as number[])?.[1]).toBeGreaterThan(45);
    await back;
    expect(await inspect(page)).toMatchObject({ current: 'shape-start', transitions: 2, direction: 'reverse', position: [30, 40] });
});

test('Jump reconstructs a destination with the same signature and no replay', async ({ page }) => {
    await openScene(page);
    await next(page);
    const animated = await next(page);
    const frame = await page.locator('#doxagon-stage iframe').elementHandle();
    const jumped = await seek(page, 'shape-morphed');
    expect(jumped.signature).toBe(animated.signature);
    expect(await frame!.evaluate((frame) => frame.isConnected)).toBe(false);
    expect(await inspect(page)).toMatchObject({ transitions: 0, current: 'shape-morphed' });
    await page.evaluate(() => window.doxagonDeck.dispatch({ type: 'PREVIOUS' }));
    expect(await inspect(page)).toMatchObject({ transitions: 1, current: 'shape-moved' });
});

test('rapid Next commands run in order without overlapping authored transitions', async ({ page }) => {
    await openScene(page);
    const results = await page.evaluate(() => Promise.all([
        window.doxagonDeck.dispatch({ type: 'NEXT' }), window.doxagonDeck.dispatch({ type: 'NEXT' }),
    ]));
    expect(results.map((item) => item.checkpointId)).toEqual(['shape-moved', 'shape-morphed']);
    expect(await inspect(page)).toMatchObject({ transitions: 2, handles: ['timers'] });
});

test('Jump cancels an in-flight transition and retires queued Next commands', async ({ page }) => {
    await openScene(page);
    const motions = page.evaluate(() => Promise.allSettled([
        window.doxagonDeck.dispatch({ type: 'NEXT' }), window.doxagonDeck.dispatch({ type: 'NEXT' }),
    ]));
    await expect.poll(async () => (await inspect(page))?.transitions).toBe(1);
    await seek(page, 'shape-start');
    await motions;
    expect(await inspect(page)).toMatchObject({ current: 'shape-start', transitions: 0, handles: ['timers'] });
    await expect(page.locator('#doxagon-stage iframe')).toHaveCount(1);
});

for (const [source, target, diagnostic] of [
    ['shape-morphed', 'shape-failed', 'authored failure'],
    ['shape-failed', 'shape-stalled', 'PRES_TRANSITION_TIMEOUT'],
    ['shape-stalled', 'shape-wrong', 'PRES_CHECKPOINT_NONDETERMINISTIC'],
]) {
    test(`${diagnostic} reconstructs the server destination and reports recovery`, async ({ page }) => {
        await openScene(page);
        await seek(page, source);
        const arrived = await next(page);
        expect(arrived.checkpointId).toBe(target);
        expect(await page.evaluate(() => window.doxagonDeck.runtime.state().diagnostics)).toEqual([expect.stringContaining(diagnostic)]);
        expect(await inspect(page)).toMatchObject({ current: target, transitions: 0 });
        expect((await seek(page, target)).signature).toBe(arrived.signature);
    });
}

test('destroy interrupts a non-settling transition and removes every realm', async ({ page }) => {
    await openScene(page);
    await seek(page, 'shape-failed');
    const motion = page.evaluate(() => window.doxagonDeck.dispatch({ type: 'NEXT' }).catch(() => null));
    await expect.poll(async () => (await inspect(page))?.transitions).toBe(1);
    await page.evaluate(() => window.doxagonDeck.runtime.destroy());
    await motion;
    await expect(page.locator('#doxagon-stage iframe')).toHaveCount(0);
});

test('reduced motion reconstructs without running arbitrary animation or simulation', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await openScene(page);
    await next(page);
    expect(await inspect(page)).toMatchObject({ current: 'shape-moved', transitions: 0, ticks: 0, handles: [] });
});

test('crossing an explicit scene boundary never retains the old realm', async ({ page }) => {
    await openScene(page);
    await seek(page, 'shape-wrong');
    const frame = await page.locator('#doxagon-stage iframe').elementHandle();
    await next(page);
    expect(await frame!.evaluate((frame) => frame.isConnected)).toBe(false);
    expect(await inspect(page)).toMatchObject({ current: 'other-scene', transitions: 0 });
});

test('contiguous snapshots animate once while duplicate polls leave the scene untouched', async ({ page }) => {
    await openScene(page);
    await issue(page, 0, 'shape-start', 'SEEK');
    await issue(page, 1, 'shape-moved');
    await issue(page, 1, 'shape-moved');
    expect(await inspect(page)).toMatchObject({ current: 'shape-moved', transitions: 1 });
});

test('a repeated snapshot reconstructs after its previous render was cancelled', async ({ page }) => {
    await openScene(page);
    await issue(page, 0, 'shape-start', 'SEEK');
    const moving = issue(page, 1, 'shape-moved').catch(() => null);
    await expect.poll(async () => (await inspect(page))?.transitions).toBe(1);
    await page.evaluate(() => window.doxagonDeck.runtime.cancel());
    await moving;
    await issue(page, 1, 'shape-moved');
    expect(await inspect(page)).toMatchObject({ current: 'shape-moved', transitions: 0 });
});

test('missed snapshots and new epochs reconstruct without replaying intermediate states', async ({ page }) => {
    await openScene(page);
    await issue(page, 0, 'shape-start', 'SEEK');
    await issue(page, 2, 'shape-morphed', 'NEXT', 'shape-moved');
    expect(await inspect(page)).toMatchObject({ current: 'shape-morphed', transitions: 0 });
    await issue(page, 0, 'shape-start', 'NEXT', 'shape-morphed', 1);
    expect(await inspect(page)).toMatchObject({ current: 'shape-start', transitions: 0 });
});

test('a newer snapshot interrupts unfinished motion and stale snapshots cannot undo it', async ({ page }) => {
    await openScene(page);
    await issue(page, 0, 'shape-start', 'SEEK');
    const moving = issue(page, 1, 'shape-moved').catch(() => null);
    await expect.poll(async () => (await inspect(page))?.transitions).toBe(1);
    await issue(page, 2, 'shape-morphed', 'NEXT', 'shape-moved');
    await moving;
    await expect(issue(page, 1, 'shape-moved')).rejects.toThrow('snapshot does not follow this session');
    expect(await inspect(page)).toMatchObject({ current: 'shape-morphed', transitions: 0 });
});
