import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

/**
 * Continuous input over the persistent scene: a sampled track receives
 * latest-value progress without becoming navigation. The realm owns its own
 * scroll geometry; the host never grows to fit it.
 */

const document = readFileSync(fileURLToPath(new URL(
    '../../../../tests/fixtures/presentations/scene-deck.offline.html', import.meta.url,
)), 'utf8');

async function openScene(page: Page) {
    await page.setContent(document, { waitUntil: 'load' });
    await expect.poll(() => page.evaluate(() => window.document.documentElement.dataset.doxagonReady)).toBe('true');
}

const inspect = (page: Page) => page.evaluate(() => window.doxagonDeck.runtime.inspect());
const state = (page: Page) => page.evaluate(() => window.doxagonDeck.state());
const sample = (page: Page, progress: number) =>
    page.evaluate((progress) => window.doxagonDeck.runtime.sample('sweep', progress), progress);

test('a sampled track moves the visual without moving the cursor', async ({ page }) => {
    await openScene(page);
    const before = await state(page);
    await sample(page, 0.5);
    expect([await state(page), await inspect(page)]).toMatchObject([before, { samples: 1, sweep: 180, current: 'shape-start' }]);
});

test('rapid samples deliver the latest value, not every value', async ({ page }) => {
    await openScene(page);
    await page.evaluate(() => Promise.all(
        Array.from({ length: 20 }, (_, index) => window.doxagonDeck.runtime.sample('sweep', index / 19)),
    ));
    const probe = await inspect(page);
    expect([probe!.sweep, (probe!.samples as number) < 20]).toEqual([330, true]);
});

test('a sample during a discrete transition lands after the cue completes', async ({ page }) => {
    await openScene(page);
    await page.evaluate(async () => {
        const moving = window.doxagonDeck.dispatch({ type: 'NEXT' });
        await new Promise((resolve) => setTimeout(resolve, 50));
        await Promise.all([moving, window.doxagonDeck.runtime.sample('sweep', 1)]);
    });
    expect(await inspect(page)).toMatchObject({ current: 'shape-moved', transitions: 1, sampled: 1, sweep: 330 });
});

test('a jump after samples reconstructs the cue exactly', async ({ page }) => {
    await openScene(page);
    const fresh = await page.evaluate(() => window.doxagonDeck.seek('shape-moved'));
    await page.evaluate(() => window.doxagonDeck.seek('shape-start'));
    await sample(page, 0.7);
    const rebuilt = await page.evaluate(() => window.doxagonDeck.seek('shape-moved'));
    expect([rebuilt.signature, (await inspect(page))!.samples]).toEqual([fresh.signature, 0]);
});

test('an unknown track is delivered and ignored, never mistaken for a cue', async ({ page }) => {
    await openScene(page);
    await page.evaluate(() => window.doxagonDeck.runtime.sample('unknown', 0.4));
    expect(await inspect(page)).toMatchObject({ samples: 0, sweep: 30, current: 'shape-start' });
});

test('sampling with no realm mounted reports that nothing was sampled', async ({ page }) => {
    await openScene(page);
    await page.evaluate(() => window.doxagonDeck.runtime.destroy());
    expect(await sample(page, 0.4)).toEqual({ sampled: false });
});

test('reduced motion still applies samples because position is content', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await openScene(page);
    await sample(page, 0.25);
    expect(await inspect(page)).toMatchObject({ sweep: 105, ticks: 0 });
});

test('the realm scrolls inside itself and the host document never grows', async ({ page }) => {
    await page.setViewportSize({ width: 480, height: 320 });
    await openScene(page);
    const viewport = await page.evaluate(() => window.doxagonDeck.runtime.viewport());
    const host = await page.evaluate(() => ({
        overflowX: window.document.documentElement.scrollWidth > window.innerWidth,
        height: window.document.documentElement.scrollHeight,
    }));
    expect([viewport!.scrollHeight > viewport!.innerHeight, host.overflowX, host.height <= 320 + 120]).toEqual([true, false, true]);
});

test('destroying the runtime with a sample pending settles cleanly', async ({ page }) => {
    await openScene(page);
    const outcome = await page.evaluate(async () => {
        const pending = window.doxagonDeck.runtime.sample('sweep', 0.9);
        await window.doxagonDeck.runtime.destroy();
        return pending.then(() => 'settled', (error) => (error as { code: string }).code);
    });
    await expect(page.locator('#doxagon-stage iframe')).toHaveCount(0);
    expect(['settled', 'PRES_NAVIGATION_CANCELLED', 'PRES_CHECKPOINT_FAILED']).toContain(outcome);
});
