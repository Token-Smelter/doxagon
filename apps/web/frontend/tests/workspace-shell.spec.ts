import { test, expect, type Page } from '@playwright/test';
import { VIEWPORTS } from './viewports';

const emptyGraph = { nodes: [], edges: [], version: 'shell-test' };

async function stubExistingApiContracts(page: Page) {
    await page.route('**/api/**', async (route) => {
        const { pathname } = new URL(route.request().url());
        let body: unknown = {};

        if (pathname === '/api/graph') body = emptyGraph;
        else if (pathname === '/api/graph/version') body = { version: emptyGraph.version };
        else if (pathname === '/api/diegeses' || pathname === '/api/phantasiai' || pathname === '/api/evidence') body = [];
        else if (pathname === '/api/pipeline/stats') {
            body = { inbox_count: 0, phantasiai: {}, doxai_count: 0, evidence_count: 0, edges_count: 0, diegeses_count: 0 };
        } else if (pathname.endsWith('/slides')) body = [];
        else if (pathname.startsWith('/api/theses/')) body = { title: 'Test thesis', subtitle: null };

        await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
    });
}

async function openRoot(page: Page, viewport: { width: number; height: number } = VIEWPORTS.desktop) {
    await page.setViewportSize(viewport);
    await stubExistingApiContracts(page);
    await page.goto('/');
    await expect(page.locator('.workspace-header')).toBeVisible();
}

test.describe('workspace shell', () => {
    test('wraps every existing route with peer workspace navigation', async ({ page }) => {
        await stubExistingApiContracts(page);

        for (const route of ['/', '/pipeline', '/present/example']) {
            await page.goto(route);
            await expect(page.locator('.workspace-header')).toBeVisible();
            await expect(page.getByRole('link', { name: 'Knowledge Graph' })).toHaveAttribute('href', '/');
            await expect(page.getByRole('link', { name: 'Presentations' })).toHaveAttribute('href', '/presentations');
        }

        await page.goto('/pipeline');
        await expect(page.locator('main')).toHaveCount(1);
    });

    test('uses one persistent ground control and retains keyboard focus', async ({ page }) => {
        await openRoot(page);

        await page.keyboard.press('Tab');
        await expect(page.locator('.brand')).toBeFocused();
        await page.keyboard.press('Tab');
        await expect(page.getByRole('link', { name: 'Knowledge Graph' })).toBeFocused();
        await page.keyboard.press('Tab');
        await expect(page.getByRole('link', { name: 'Presentations' })).toBeFocused();
        await page.keyboard.press('Tab');

        const toggle = page.getByRole('button', { name: 'Use nigredo ground' });
        await expect(toggle).toBeFocused();
        await page.keyboard.press('Enter');
        await expect(page.locator('body')).toHaveClass(/dox-invert/);
        await expect(page.getByRole('button', { name: 'Use cream ground' })).toHaveAttribute('aria-pressed', 'true');
        await expect.poll(() => page.evaluate(() => localStorage.getItem('doxagon-ground'))).toBe('nigredo');

        await page.reload();
        await expect(page.locator('body')).toHaveClass(/dox-invert/);
        await expect(page.getByRole('button', { name: 'Use cream ground' })).toHaveAttribute('aria-pressed', 'true');
    });

    for (const [name, viewport] of Object.entries(VIEWPORTS)) {
        test(`has no document horizontal overflow at ${name}`, async ({ page }) => {
            await openRoot(page, viewport);
            await expect.poll(() => page.evaluate(
                () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
            )).toBe(true);
        });
    }

    test('uses a two-row compact header at 320px', async ({ page }) => {
        await openRoot(page, VIEWPORTS.mobile_small);
        const navigation = page.locator('.workspace-nav');
        const header = page.locator('.workspace-header');
        const [navigationBox, headerBox] = await Promise.all([navigation.boundingBox(), header.boundingBox()]);

        expect(navigationBox?.y).toBeGreaterThan(headerBox?.y ?? 0);
        await expect(page.locator('.ground-label')).toBeHidden();
    });

    test('self-hosts structural type roles without runtime font requests', async ({ page }) => {
        const externalFontRequests: string[] = [];
        page.on('request', (request) => {
            if (/fonts\.(googleapis|gstatic)\.com/.test(request.url())) externalFontRequests.push(request.url());
        });
        await openRoot(page);
        await expect.poll(() => page.evaluate(async () => {
            const checks = await Promise.all([
                document.fonts.load('16px "Space Grotesk"'),
                document.fonts.load('16px "Newsreader"'),
                document.fonts.load('16px "JetBrains Mono"'),
            ]);
            return checks.every((faces) => faces.length > 0);
        })).toBe(true);
        await expect(page.locator('.graph-context h1')).toHaveCSS('font-family', /Space Grotesk/);
        await expect(page.locator('.graph-context p')).toHaveCSS('font-family', /Newsreader/);
        await expect(page.getByLabel('Search')).toHaveCSS('font-family', /JetBrains Mono/);
        expect(externalFontRequests).toEqual([]);
    });

    test('captures all required viewports on cream and nigredo work grounds', async ({ page }, testInfo) => {
        await page.addInitScript(() => localStorage.setItem('doxagon-ground', 'cream'));
        await openRoot(page, VIEWPORTS.desktop);
        const initialFrame = await page.locator('.workspace-header').evaluate((element) => getComputedStyle(element).backgroundColor);

        for (const [viewportName, viewport] of Object.entries(VIEWPORTS)) {
            await page.setViewportSize(viewport);
            for (const ground of ['cream', 'nigredo'] as const) {
                const body = page.locator('body');
                const inverted = await body.evaluate((element) => element.classList.contains('dox-invert'));
                if ((ground === 'nigredo') !== inverted) {
                    await page.locator('.ground-toggle').click();
                }
                await expect.poll(() => page.evaluate(
                    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
                )).toBe(true);
                await expect(page.locator('.workspace-header')).toHaveCSS('background-color', initialFrame);
                const path = testInfo.outputPath(`instrument-${ground}-${viewportName}.png`);
                await page.screenshot({ path });
                await testInfo.attach(`instrument-${ground}-${viewportName}`, { path, contentType: 'image/png' });
            }
        }
    });
});
