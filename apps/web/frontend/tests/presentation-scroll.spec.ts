import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';

/**
 * The scroll article: host scroll position selects cues in a pinned realm.
 * Neighbouring cues play their authored transitions; skipped cues reconstruct;
 * the realm's own viewport never changes because the host scrolled.
 */

declare global {
    interface Window {
        doxagonScroll: {
            currentCue(): string | null;
            readingLine(): number;
            cues: string[];
            settled(): Promise<unknown>;
        };
    }
}

const ARTICLE_PATH = fileURLToPath(new URL(
    '../../../../tests/fixtures/presentations/scene-deck.scroll.html', import.meta.url,
));
const article = readFileSync(ARTICLE_PATH, 'utf8');

async function openArticle(page: Page, hash = '') {
    await page.setViewportSize({ width: 1280, height: 800 });
    // A deep link must arrive the way a browser carries it. The artifact's CSP
    // pins its one script by hash, so no test-injected inline script can run;
    // a real file navigation with a fragment is the honest way in.
    if (hash) await page.goto(`${pathToFileURL(ARTICLE_PATH).href}${hash}`, { waitUntil: 'load' });
    else await page.setContent(article, { waitUntil: 'load' });
    await expect.poll(
        () => page.evaluate(() => `${document.documentElement.dataset.doxagonReady ?? ''}${document.getElementById('doxagon-stage')?.dataset.error ?? ''}`),
        { timeout: 15000 },
    ).toBe('true');
}

const cue = (page: Page) => page.evaluate(() => window.doxagonScroll.currentCue());

/** The realm's own viewport, once one is mounted and satisfies `ready`. */
async function measureRealm(page: Page, ready: (probe: { innerHeight: number; scrollHeight: number }) => boolean = () => true) {
    let measured: { innerWidth: number; innerHeight: number; scrollY: number; scrollHeight: number } | null = null;
    await expect.poll(async () => {
        measured = await page.evaluate(() => window.doxagonDeck.runtime.viewport());
        return measured !== null && ready(measured);
    }).toBe(true);
    return measured!;
}
const inspect = (page: Page) => page.evaluate(() => window.doxagonDeck.runtime.inspect());

/** Scroll so the named cue's section sits just past the reading line, then let the shell settle. */
async function scrollToCue(page: Page, id: string) {
    await page.evaluate((id) => {
        const section = document.querySelector(`[data-cue="${id}"]`)!;
        window.scrollTo(0, window.scrollY + section.getBoundingClientRect().top - window.doxagonScroll.readingLine() + 2);
    }, id);
    await expect.poll(() => cue(page)).toBe(id);
    await page.evaluate(() => window.doxagonScroll.settled());
}

test('the article opens on the first cue with the stage pinned to the viewport', async ({ page }) => {
    await openArticle(page);
    await page.evaluate(() => window.scrollTo(0, 200));
    const stageTop = await page.locator('#doxagon-stage').evaluate((node) => node.getBoundingClientRect().top);
    expect([await cue(page), stageTop]).toEqual(['shape-start', 0]);
});

test('scrolling to the neighbouring cue plays its authored transition in the same realm', async ({ page }) => {
    await openArticle(page);
    const frame = await page.locator('#doxagon-stage iframe').elementHandle();
    await scrollToCue(page, 'shape-moved');
    expect([await frame!.evaluate((node) => node.isConnected), (await inspect(page))!.transitions]).toEqual([true, 1]);
});

test('scrolling past a cue reconstructs the destination instead of replaying', async ({ page }) => {
    await openArticle(page);
    await scrollToCue(page, 'shape-morphed');
    expect(await inspect(page)).toMatchObject({ current: 'shape-morphed', transitions: 0 });
});

test('scrolling back up plays the separately authored reverse transition', async ({ page }) => {
    await openArticle(page);
    await scrollToCue(page, 'shape-moved');
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect.poll(() => cue(page)).toBe('shape-start');
    await page.evaluate(() => window.doxagonScroll.settled());
    expect(await inspect(page)).toMatchObject({ transitions: 2, direction: 'reverse' });
});

test('a deep link opens the article on the named cue', async ({ page }) => {
    await openArticle(page, '#cue-shape-morphed');
    const stageError = await page.locator('#doxagon-stage').getAttribute('data-error');
    expect([await cue(page), stageError]).toEqual(['shape-morphed', null]);
});

test('the location hash follows the current cue', async ({ page }) => {
    await openArticle(page);
    await scrollToCue(page, 'shape-moved');
    expect(await page.evaluate(() => window.location.hash)).toBe('#cue-shape-moved');
});

test('arrow keys step one cue forward and back', async ({ page }) => {
    await openArticle(page);
    await page.keyboard.press('ArrowDown');
    await expect.poll(() => cue(page)).toBe('shape-moved');
    await page.keyboard.press('ArrowUp');
    await expect.poll(() => cue(page)).toBe('shape-start');
});

test('a burst of scroll events settles on the final cue without replaying every step', async ({ page }) => {
    await openArticle(page);
    await page.evaluate(() => {
        const target = document.querySelector('[data-cue="shape-morphed"]')!;
        const end = window.scrollY + target.getBoundingClientRect().top - window.doxagonScroll.readingLine() + 2;
        for (let step = 1; step <= 30; step += 1) window.scrollTo(0, (end * step) / 30);
    });
    await expect.poll(() => cue(page)).toBe('shape-morphed');
    await page.evaluate(() => window.doxagonScroll.settled());
    expect((await inspect(page))!.transitions as number).toBeLessThanOrEqual(2);
});

test('host scrolling never changes the realm\'s own viewport', async ({ page }) => {
    await openArticle(page);
    const before = await measureRealm(page, (probe) => probe.scrollHeight > probe.innerHeight);
    await page.evaluate(() => window.scrollTo(0, 1500));
    // Crossing cues rebuilds realms; between teardown and creation no realm is
    // active, so measure once navigation has settled on a mounted realm.
    await page.evaluate(() => window.doxagonScroll.settled());
    // Crossing a cue rebuilds the realm; between teardown and creation there is
    // nothing to measure, so wait for a mounted realm rather than a null.
    const after = await measureRealm(page);
    const frame = await page.locator('#doxagon-stage iframe').evaluate((node) => node.getBoundingClientRect().height);
    // The realm's innerHeight is its own frame box, before and after the host
    // scrolled; a stretched-to-content realm would report a far larger number.
    expect([after!.innerHeight, Math.abs(before!.innerHeight - frame) < 2, before!.scrollHeight > before!.innerHeight])
        .toEqual([before!.innerHeight, true, true]);
});

test('the article carries no speaker notes', async () => {
    // Phrases that occur only in the fixture's notes files, never in a label.
    expect(article).not.toMatch(/Name the three things|ends on the destination the server named/);
});
