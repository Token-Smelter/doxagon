import { test, expect } from '@playwright/test';
import { VIEWPORTS } from '../viewports';

function contrastRatio(first: string, second: string) {
    const luminance = (color: string) => {
        const channels = color.match(/\d+/g)!.slice(0, 3).map(Number).map((channel) => {
            const normalized = channel / 255;
            return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
        });
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    };
    const [lighter, darker] = [luminance(first), luminance(second)].sort((a, b) => b - a);
    return (lighter + 0.05) / (darker + 0.05);
}

test.describe('DetailPanel mobile bottom sheet', () => {
    async function openPanel(page: import('@playwright/test').Page, activation: 'pointer' | 'keyboard' = 'pointer') {
        await page.route('**/api/graph', (route) => route.fulfill({ json: {
            version: 'inspector-fixture',
            nodes: [{ slug: 'alpha', title: 'Alpha', belief: 'Alpha belief', tags: ['logic'], evidence: [] }],
            edges: []
        } }));
        await page.route('**/api/graph/version', (route) => route.fulfill({ json: { version: 'inspector-fixture' } }));
        await page.route('**/api/diegeses', (route) => route.fulfill({ json: [] }));
        await page.route('**/api/doxai/alpha', (route) => route.fulfill({ json: {
            slug: 'alpha', title: 'Alpha', belief: 'Alpha belief', tags: ['logic'], evidence: [],
            content: '# Grounded content\n\n```mermaid\ngraph LR\nA --> B\n```', incoming: [], outgoing: [], diegeses: []
        } }));
        await page.route('**/api/theses/slide-usages?doxa=alpha', (route) => route.fulfill({ json: [{
            thesis_slug: 'thesis-one', thesis_title: 'Thesis One', slide_slug: 'opening', slide_number: 1, slide_title: 'Opening'
        }] }));
        await page.goto('/');
        if (activation === 'keyboard') {
            await page.locator('.graph-svg').focus();
            await page.keyboard.press('Home');
            await page.keyboard.press('Enter');
        } else {
            await page.getByRole('button', { name: /Alpha belief/ }).click();
        }
        await expect(page.locator('.detail-panel')).toBeVisible();
    }

    test('mobile: panel is full-width bottom sheet at 375px', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await openPanel(page);

        const panel = page.locator('.detail-panel.mobile');
        await expect(panel).toBeVisible();

        const box = await panel.boundingBox();
        expect(box).not.toBeNull();
        // Full viewport width
        expect(box!.width).toBeCloseTo(375, -1);
        // Positioned at the bottom (bottom edge == viewport height)
        expect(box!.y + box!.height).toBeCloseTo(667, -1);
        // Drag handle is visible on mobile
        await expect(panel.locator('.drag-handle')).toBeVisible();
        await expect(page.getByRole('separator', { name: 'Doxa details for alpha' })).toHaveCount(0);
    });

    test('mobile: dialog receives focus and controls meet the touch target', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await openPanel(page);

        const panel = page.locator('.detail-panel');
        await expect(panel).toBeFocused();
        const closeBox = await panel.locator('.close-btn').boundingBox();
        expect(closeBox?.width).toBeGreaterThanOrEqual(44);
        expect(closeBox?.height).toBeGreaterThanOrEqual(44);
    });

    test('safe presentation link preserves explicit thesis, slide, and encoded graph return', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await openPanel(page);

        const link = page.getByRole('link', { name: /Thesis One/ });
        await expect(link).toHaveAttribute('href', /\/presentations\?thesis=thesis-one&slide=opening&return=/);
        await expect(link).toHaveAttribute('href', /node%3Dalpha/);
    });

    test('semantic grounds invert without horizontal overflow', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await openPanel(page);
        const panel = page.locator('.detail-panel');
        const cream = await panel.evaluate((element) => getComputedStyle(element).backgroundColor);
        const creamText = await panel.evaluate((element) => getComputedStyle(element).color);
        expect(contrastRatio(cream, creamText)).toBeGreaterThanOrEqual(4.5);
        await page.evaluate(() => document.body.classList.add('dox-invert'));
        const nigredo = await panel.evaluate((element) => getComputedStyle(element).backgroundColor);
        const nigredoText = await panel.evaluate((element) => getComputedStyle(element).color);
        expect(nigredo).not.toBe(cream);
        expect(contrastRatio(nigredo, nigredoText)).toBeGreaterThanOrEqual(4.5);
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
    });

    test('Mermaid diagrams re-theme when the semantic ground changes', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await openPanel(page);
        const diagram = page.locator('.mermaid-diagram svg');
        await expect(diagram).toBeVisible();
        const creamSvg = await diagram.evaluate((element) => element.outerHTML);
        await page.evaluate(() => document.body.classList.add('dox-invert'));
        await expect.poll(() => diagram.evaluate((element) => element.outerHTML)).not.toBe(creamSvg);
    });

    test('desktop keyboard selection retains graph focus while inspector opens as complementary content', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.desktop);
        await openPanel(page, 'keyboard');
        await expect(page.getByRole('button', { name: /Alpha belief; 0 evidence references/ })).toBeFocused();
        await expect(page.getByRole('complementary', { name: 'Doxa details for alpha' })).toBeVisible();
    });

    test('desktop: panel is 400px wide on right side at 1280px', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.desktop);
        await openPanel(page);

        const panel = page.locator('.detail-panel');
        await expect(panel).toBeVisible();
        // Must not have .mobile class on desktop
        await expect(panel).not.toHaveClass(/mobile/);

        const box = await panel.boundingBox();
        expect(box).not.toBeNull();
        // Width is 400px
        expect(box!.width).toBeCloseTo(400, -1);
        // Right edge is at viewport right
        expect(box!.x + box!.width).toBeCloseTo(1280, -1);

        // Drag handle is absent on desktop
        await expect(page.locator('.detail-panel .drag-handle')).not.toBeVisible();
    });

    test('desktop: separator pointer drag changes the panel width without horizontal overflow', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.desktop);
        await openPanel(page);

        const separator = page.getByRole('separator', { name: 'Doxa details for alpha' });
        await expect(separator).toHaveAttribute('aria-orientation', 'vertical');
        await expect(separator).toHaveAttribute('aria-controls', 'doxa-detail-panel');
        await expect(page.getByRole('complementary', { name: 'Doxa details for alpha' })).toHaveAttribute('id', 'doxa-detail-panel');
        await expect(separator).toHaveAttribute('aria-valuemin', '320');
        await expect(separator).toHaveAttribute('aria-valuemax', '720');
        await expect(separator).toHaveAttribute('aria-valuenow', '400');

        const handle = await separator.boundingBox();
        expect(handle).not.toBeNull();
        const startX = handle!.x + handle!.width / 2;
        await page.mouse.move(startX, handle!.y + 40);
        await page.mouse.down();
        await page.mouse.move(startX - 160, handle!.y + 40);
        await page.mouse.up();

        const panel = page.locator('.detail-panel');
        await expect.poll(async () => (await panel.boundingBox())!.width).toBeCloseTo(560, -1);
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(VIEWPORTS.desktop.width);
    });

    test('desktop: separator keyboard controls persist a clamped preference', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.desktop);
        await openPanel(page);

        const separator = page.getByRole('separator', { name: 'Doxa details for alpha' });
        const panel = page.locator('.detail-panel');
        const initialHandle = await separator.boundingBox();
        expect(initialHandle).not.toBeNull();

        await separator.focus();
        await page.keyboard.press('ArrowRight');
        await expect(separator).toHaveAttribute('aria-valuenow', '384');
        await expect.poll(async () => (await separator.boundingBox())!.x).toBeCloseTo(initialHandle!.x + 16, -1);
        await page.keyboard.press('ArrowLeft');
        await expect(separator).toHaveAttribute('aria-valuenow', '400');
        await expect.poll(async () => (await separator.boundingBox())!.x).toBeCloseTo(initialHandle!.x, -1);
        await expect.poll(async () => (await panel.boundingBox())!.width).toBeCloseTo(400, -1);
        await page.keyboard.press('Home');
        await expect(separator).toHaveAttribute('aria-valuenow', '320');
        await page.keyboard.press('End');
        await expect(separator).toHaveAttribute('aria-valuenow', '720');

        await page.setViewportSize({ width: 900, height: VIEWPORTS.desktop.height });
        await expect(separator).toHaveAttribute('aria-valuemax', '580');
        await expect(separator).toHaveAttribute('aria-valuenow', '580');
        await page.setViewportSize(VIEWPORTS.desktop);
        await expect(separator).toHaveAttribute('aria-valuenow', '720');

        await separator.dblclick();
        await expect(separator).toHaveAttribute('aria-valuenow', '400');
        await page.reload();
        await expect(separator).toHaveAttribute('aria-valuenow', '400');
    });
});
