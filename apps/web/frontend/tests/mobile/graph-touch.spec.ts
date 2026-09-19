import { test, expect } from '@playwright/test';
import { VIEWPORTS } from '../viewports';

test.describe('Graph touch interaction — mobile layout', () => {
    test('graph canvas is visible and fills viewport width at 375px', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await page.goto('/');

        const graphContainer = page.locator('.graph-container');
        await expect(graphContainer).toBeVisible({ timeout: 10000 });

        const containerBox = await graphContainer.boundingBox();
        expect(containerBox).not.toBeNull();
        // Graph should fill the available width (within a few px for scrollbars/borders)
        expect(containerBox!.width).toBeGreaterThan(VIEWPORTS.mobile_medium.width * 0.9);
    });

    test('no horizontal scrollbar on graph area at 375px', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await page.goto('/');

        await page.locator('.graph-container').waitFor({ state: 'visible', timeout: 10000 });

        const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
        const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
        expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
    });

    test('no horizontal scrollbar on graph area at 320px', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_small);
        await page.goto('/');

        await page.locator('.graph-container').waitFor({ state: 'visible', timeout: 10000 });

        const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
        const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
        expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
    });

    test('graph renders and fills viewport on desktop (regression)', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.desktop);
        await page.goto('/');

        const graphContainer = page.locator('.graph-container');
        await expect(graphContainer).toBeVisible({ timeout: 10000 });

        const containerBox = await graphContainer.boundingBox();
        expect(containerBox).not.toBeNull();
        expect(containerBox!.width).toBeGreaterThan(400);
    });

    test('attaches the nigredo graph at 375×667', async ({ page }, testInfo) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await page.route('**/api/graph', (route) => route.fulfill({ json: {
            version: 'nigredo-screenshot',
            nodes: [
                { slug: 'ground', title: 'Ground', belief: 'Ground the claim', tags: [], evidence: [] },
                { slug: 'proof', title: 'Proof', belief: 'Inspect the evidence', tags: [], evidence: [] }
            ],
            edges: [{ source: 'ground', target: 'proof', type: 'grounds', alias: 'grounds' }]
        } }));
        await page.route('**/api/graph/version', (route) => route.fulfill({ json: { version: 'nigredo-screenshot' } }));
        await page.route('**/api/diegeses', (route) => route.fulfill({ json: [] }));
        await page.goto('/');
        await page.getByRole('button', { name: 'Use nigredo ground' }).click();
        await expect(page.locator('body')).toHaveClass(/dox-invert/);
        await expect(page.locator('.graph-container')).toBeVisible();

        const path = testInfo.outputPath('slice-3-graph-nigredo-375x667.png');
        await page.screenshot({ path });
        await testInfo.attach('slice-3-graph-nigredo-375x667.png', { path, contentType: 'image/png' });
    });

    test.describe('touch-capable context', () => {
        test.use({ hasTouch: true, isMobile: true });

        test('a mobile tap selects a producer-compatible doxa', async ({ page }) => {
            await page.setViewportSize(VIEWPORTS.mobile_medium);
            await page.route('**/api/graph', (route) => route.fulfill({ json: {
                version: 'touch-fixture',
                nodes: [{ slug: 'touch-doxa', title: 'Touch Doxa', belief: 'Touch belief', tags: [], evidence: [] }],
                edges: []
            } }));
            await page.route('**/api/graph/version', (route) => route.fulfill({ json: { version: 'touch-fixture' } }));
            await page.route('**/api/diegeses', (route) => route.fulfill({ json: [] }));
            await page.goto('/');
            const doxa = page.getByRole('button', { name: /Touch belief/ });
            await expect(doxa).toBeVisible();
            await doxa.tap();
            await expect(doxa).toHaveAttribute('tabindex', '0');
            await expect(page.locator('.node-label-card')).toContainText('Touch belief');
        });
    });
});
