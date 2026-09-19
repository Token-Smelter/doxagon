import { expect, test, type Page } from '@playwright/test';
import { startVaultServer, useRealVault, type VaultServer } from './support/vaultServer';

let server: VaultServer;
test.beforeAll(async () => { server = await startVaultServer(); });
test.afterAll(async () => { await server?.stop(); });

async function openScene(page: Page, route = '/presentations?thesis=scene') {
    await useRealVault(page.context(), server);
    await page.goto(route);
    await expect(page.getByTestId('preview-checkpoint')).toHaveText('shape-start');
}

const visibleRealm = '.stage .realm iframe:not([aria-hidden])';

test('editor Next executes authored motion from the real server navigation snapshot', async ({ page }) => {
    await openScene(page);
    const frame = await page.locator(visibleRealm).elementHandle();
    const response = page.waitForResponse((response) => response.url().endsWith('/actions'));
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    expect((await (await response).json()).navigation).toEqual({ type: 'NEXT', from: 'shape-start' });
    await expect(page.getByTestId('preview-checkpoint')).toHaveText('shape-moved');
    expect(await frame!.evaluate((frame) => frame.isConnected)).toBe(true);
    await expect(page.frameLocator(visibleRealm).locator('rect')).toHaveAttribute('x', '150');
});

test('audience polling traverses once and does not reset a persistent scene on duplicate snapshots', async ({ page }) => {
    await openScene(page);
    await page.getByRole('button', { name: 'Present', exact: true }).click();
    const audience = page.getByTestId('audience-display');
    await expect(audience.locator('.realm')).toHaveAttribute('data-checkpoint', 'shape-start');
    const frame = await audience.locator('iframe').elementHandle();
    await page.keyboard.press('ArrowRight');
    await expect(audience.locator('.realm')).toHaveAttribute('data-checkpoint', 'shape-moved');
    for (let count = 0; count < 3; count += 1) {
        await page.waitForResponse((response) => /\/sessions\/[^/]+$/.test(new URL(response.url()).pathname));
    }
    expect(await frame!.evaluate((frame) => frame.isConnected)).toBe(true);
    await expect(audience.locator('.realm')).toHaveAttribute('data-checkpoint', 'shape-moved');
});

test('outline Jump interrupts a non-settling animation without showing the abandoned destination', async ({ page }) => {
    await openScene(page);
    await page.getByRole('button', { name: 'Slide 2: Recovery probes', exact: true }).click();
    await page.locator('.outline-select[data-checkpoint="shape-failed"]').click();
    await expect(page.getByTestId('preview-checkpoint')).toHaveText('shape-failed');
    const action = page.waitForResponse((response) => response.url().endsWith('/actions'));
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await action;
    await page.locator('.outline-select[data-checkpoint="shape-start"]').click();
    await expect(page.getByTestId('preview-checkpoint')).toHaveText('shape-start');
    await expect(page.getByTestId('preview-failure')).toHaveCount(0);
    await expect(page.frameLocator(visibleRealm).locator('rect')).toHaveAttribute('x', '30');
});

test('presenter controls retain the scene while notes and position follow the server destination', async ({ page }) => {
    await openScene(page, '/present/scene');
    const frame = await page.locator('.realm iframe').elementHandle();
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(page.getByTestId('presenter-position')).toContainText('step 2 of 3');
    expect(await frame!.evaluate((frame) => frame.isConnected)).toBe(true);
    await expect(page.getByTestId('preview-checkpoint')).toHaveText('shape-moved');
});

test('a blocked presenter window is reported with a link instead of failing silently', async ({ page }) => {
    await openScene(page);
    // Stand in for a popup blocker: window.open yields null as a blocker does.
    await page.evaluate(() => { window.open = () => null; });
    await page.getByRole('button', { name: 'Present', exact: true }).click();
    const notice = page.getByTestId('presenter-blocked');
    await expect(notice).toBeVisible();
    await expect(notice.getByRole('link', { name: 'Open the presenter view' }))
        .toHaveAttribute('href', /\/present\/scene\?session=session_/);
    await page.getByRole('button', { name: 'Exit presentation' }).click();
    await expect(page.getByTestId('audience-display')).toHaveCount(0);
});

test('presenting a document reads its cues as a scrolling script with the current one emphasized', async ({ page }) => {
    await useRealVault(page.context(), server);
    await page.goto('/present/document');
    const passages = page.getByTestId('presenter-notes').locator('.passage');
    await expect(passages).toHaveCount(3);
    // The whole document's script is in view: current emphasized, next below.
    await expect(passages.nth(0)).toHaveAttribute('aria-current', 'step');
    await expect(passages.nth(1)).toContainText('Name the three regions');
    await expect(page.getByTestId('presenter-position')).toContainText('1 of 3');

    await page.getByRole('button', { name: 'Next', exact: true }).click();

    // Advancing moves the emphasis inside the document; the deck did not move.
    // The cursor is server-issued, so wait for the position it published.
    await expect(page.getByTestId('presenter-position')).toContainText('2 of 3');
    await expect(passages.nth(1)).toHaveAttribute('aria-current', 'step');
    await expect(passages.nth(0)).toHaveClass(/is-spoken/);
    await expect(page.getByTestId('presenter-next')).toContainText('closing');
});

test('presenter notes read as one scrolling script per slide with the current passage emphasized', async ({ page }) => {
    await openScene(page, '/present/scene');
    const pane = page.getByTestId('presenter-notes');
    const passages = pane.locator('.passage');
    // The whole slide's script is visible at once, one passage per Step, and
    // the first Step's passage is the one being read.
    await expect(passages).toHaveCount(3);
    await expect(passages.nth(0)).toHaveAttribute('aria-current', 'step');
    await expect(passages.nth(1)).toContainText('The image follows the square');

    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(page.getByTestId('preview-checkpoint')).toHaveText('shape-moved');
    // Advancing moves the emphasis, not the page: the same three passages
    // remain, the first is now spoken, and the second is current.
    await expect(passages).toHaveCount(3);
    await expect(passages.nth(1)).toHaveAttribute('aria-current', 'step');
    await expect(passages.nth(0)).toHaveClass(/is-spoken/);
    const current = await passages.nth(1).evaluate((node) => getComputedStyle(node).color);
    const spoken = await passages.nth(0).evaluate((node) => getComputedStyle(node).color);
    expect(current).not.toBe(spoken);

    // A new slide is a new script. Its three Steps carry one copied note, which
    // reads once rather than three times and stays current across all of them.
    await page.getByTestId('presenter-steps').locator('button[data-checkpoint="shape-stalled"]').click();
    await expect(page.getByTestId('preview-checkpoint')).toHaveText('shape-stalled');
    await expect(passages).toHaveCount(1);
    await expect(passages.nth(0)).toHaveAttribute('aria-current', 'step');
    await expect(passages.nth(0)).toContainText('Recovery probes');
});

for (const width of [1440, 390]) {
    test(`slide headers collapse by keyboard and playback expands the active slide at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await useRealVault(page.context(), server);
        await page.goto('/presentations?thesis=stock');
        await expect(page.getByTestId('preview-checkpoint')).toHaveText('slide-opening-step-0');
        if (width < 1024) await page.getByRole('navigation', { name: 'Workspace region' }).getByRole('button', { name: 'Steps', exact: true }).click();
        const first = page.getByRole('button', { name: 'Slide 1: Opening choreography', exact: true });
        const second = page.getByRole('button', { name: 'Slide 2: Motion choreography', exact: true });
        await first.focus();
        await page.keyboard.press('Enter');
        await expect(first).toHaveAttribute('aria-expanded', 'false');
        await expect(page.locator('.outline-select[data-checkpoint="slide-opening-step-0"]')).toBeHidden();
        await page.keyboard.press('ArrowRight');
        await expect(first).toHaveAttribute('aria-expanded', 'true');
        await expect(page.getByTestId('preview-checkpoint')).toHaveText('slide-opening-step-1');
        await page.keyboard.press('ArrowRight');
        await expect(page.getByTestId('preview-checkpoint')).toHaveText('slide-opening-step-2');
        await page.keyboard.press('ArrowRight');
        await expect(second).toHaveAttribute('aria-expanded', 'true');
        await expect(page.locator('.outline-select[data-checkpoint="slide-motion-step-0"]')).toHaveAttribute('aria-current', 'true');
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        await page.screenshot({ path: `/tmp/doxagon-slide-groups-${width}.png` });
    });
}

