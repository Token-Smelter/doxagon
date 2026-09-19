import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';

/**
 * Document mode: the authored page owns the viewport, the scroll, and the
 * layout. These prove the capabilities a bespoke article needs — sticky
 * full-bleed scenes, overlaid prose, a continuous simulation, scrubbed motion,
 * hover interaction — not a resemblance to any particular source page.
 */

declare global {
    interface Window {
        doxagonDocument: {
            cues(): string[];
            currentCue(): string | null;
            step(delta: number): Promise<void>;
            travel(cue: string): Promise<unknown>;
        };
    }
}

const PATH = fileURLToPath(new URL(
    '../../../../tests/fixtures/presentations/document-deck.document.html', import.meta.url,
));
const article = readFileSync(PATH, 'utf8');

async function openDocument(page: Page, hash = '') {
    await page.setViewportSize({ width: 1280, height: 800 });
    if (hash) await page.goto(`${pathToFileURL(PATH).href}${hash}`, { waitUntil: 'load' });
    else await page.setContent(article, { waitUntil: 'load' });
    await expect.poll(
        () => page.evaluate(() => document.documentElement.dataset.doxagonReady),
        { timeout: 15000 },
    ).toBe('true');
}

const realm = (page: Page) => page.frameLocator('#doxagon-stage iframe');
const inspect = (page: Page) => page.evaluate(() => window.doxagonDeck.runtime.inspect());
/** Scroll inside the realm, the way a reader does. */
const scrollRealm = (page: Page, top: number) =>
    realm(page).locator('body').evaluate((_, top) => window.scrollTo(0, top), top);

test('the authored page owns the viewport and scrolls itself', async ({ page }) => {
    await openDocument(page);
    const view = await page.evaluate(() => window.doxagonDeck.runtime.viewport());
    const host = await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight + 1);
    // The realm is a real viewport with a real long page inside it.
    expect([view!.innerHeight, view!.scrollHeight > view!.innerHeight * 3, host]).toEqual([800, true, true]);
});

test('a sticky full-bleed scene stays pinned while its prose scrolls over it', async ({ page }) => {
    await openDocument(page);
    await scrollRealm(page, 900);
    const canvas = await realm(page).locator('#field').boundingBox();
    const step = await realm(page).locator('.step').first().boundingBox();
    // Canvas pinned to the top of the realm viewport, prose moved past it.
    expect([Math.round(canvas!.y), canvas!.width, step!.y < canvas!.y + canvas!.height]).toEqual([0, 1280, true]);
});

test('scrolling scrubs the authored motion without moving the deck cursor', async ({ page }) => {
    await openDocument(page);
    const before = await page.evaluate(() => window.doxagonDeck.state());
    await scrollRealm(page, 1500);
    await expect.poll(async () => (await inspect(page))!.drift as number).toBeGreaterThan(0.2);
    // Continuous input is content: it never advances the session cursor.
    expect(await page.evaluate(() => window.doxagonDeck.state())).toEqual(before);
});

test('the simulation keeps running while the reader rests', async ({ page }) => {
    await openDocument(page);
    const first = (await inspect(page))!.ticks as number;
    await page.waitForTimeout(300);
    expect((await inspect(page))!.ticks as number).toBeGreaterThan(first);
});

test('the realm reports the cue its own layout selected', async ({ page }) => {
    await openDocument(page);
    await scrollRealm(page, 3000);
    await expect.poll(() => page.evaluate(() => window.doxagonDocument.currentCue())).toBe('clusters');
    expect(await page.evaluate(() => document.documentElement.dataset.doxagonCue)).toBe('clusters');
});

test('Next travels to the next cue inside the same document', async ({ page }) => {
    await openDocument(page);
    await page.evaluate(() => window.doxagonDocument.travel('field'));
    await page.evaluate(() => window.doxagonDocument.step(1));
    await expect.poll(() => page.evaluate(() => window.doxagonDocument.currentCue()), { timeout: 10000 }).toBe('clusters');
    // Travelling within a document is not a checkpoint change.
    expect((await page.evaluate(() => window.doxagonDeck.state())).sequence).toBe(1);
});

test('author interaction works without the player intercepting it', async ({ page }) => {
    await openDocument(page);
    await page.evaluate(() => window.doxagonDocument.travel('clusters'));
    await realm(page).locator('.legend li[data-region="1"]').hover();
    await expect.poll(async () => (await inspect(page))!.hovered).toBe(1);
});

test('a deep link opens the document at the named cue', async ({ page }) => {
    await openDocument(page, '#clusters');
    await expect.poll(() => page.evaluate(() => window.doxagonDocument.currentCue()), { timeout: 10000 }).toBe('clusters');
});

test('the reader keeps native text selection and keyboard scrolling', async ({ page }) => {
    await openDocument(page);
    await realm(page).locator('.lede').click();
    await page.keyboard.press('ArrowDown');
    await page.waitForTimeout(150);
    const scrolled = await page.evaluate(() => window.doxagonDeck.runtime.viewport());
    // ArrowDown belongs to the reader inside the document; the shell binds only
    // ArrowRight/ArrowLeft, so the page itself moved.
    expect(scrolled!.scrollY).toBeGreaterThan(0);
});

test('adopting a snapshot travels inside the document rather than rebuilding it', async ({ page }) => {
    await openDocument(page);
    const frame = await page.locator('#doxagon-stage iframe').elementHandle();
    const before = await inspect(page);
    // Exactly what a follower does with a server-issued cue: same checkpoint,
    // new position. The realm must scroll, not be torn down and rebuilt.
    await page.evaluate(() => window.doxagonDeck.runtime.adopt({
        schema: 'doxagon.presentation-snapshot/2', session_id: 'follower', deck_revision: window.doxagonDeck.revision,
        epoch: 0, sequence: 1, checkpoint_id: 'field-document', cue: 'clusters',
        issued_at: '2026-09-06T00:00:00Z', navigation: null,
    }));
    await expect.poll(() => page.evaluate(() => window.doxagonDocument.currentCue()), { timeout: 10000 }).toBe('clusters');
    expect([await frame!.evaluate((node) => node.isConnected), (await inspect(page))!.ticks as number >= (before!.ticks as number)])
        .toEqual([true, true]);
});

test('reduced motion keeps the content and drops the ambient simulation', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await openDocument(page);
    await page.waitForTimeout(250);
    const probe = await inspect(page);
    await expect(realm(page).locator('h1')).toBeVisible();
    expect([probe!.ticks, probe!.handles]).toEqual([0, []]);
});
