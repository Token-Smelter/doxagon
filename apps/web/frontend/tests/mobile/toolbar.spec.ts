import { test, expect } from '@playwright/test';
import { VIEWPORTS } from '../viewports';

async function openToolbar(page: import('@playwright/test').Page) {
    await page.goto('/');
    await expect(page.locator('.toolbar')).toBeVisible({ timeout: 10_000 });
}

for (const [name, viewport] of [
    ['mobile 375px', VIEWPORTS.mobile_medium],
    ['desktop 1280px', VIEWPORTS.desktop],
] as const) {
    test.describe(`Toolbar — ${name}`, () => {
        test.use({ viewport });

        test.beforeEach(async ({ page }) => openToolbar(page));

        test('keeps Search, Scope, and Focus primary', async ({ page }) => {
            await expect(page.getByRole('searchbox', { name: 'Search', exact: true })).toBeVisible();
            await expect(page.getByLabel('Diegesis')).toBeVisible();
            await expect(page.getByRole('button', { name: /Focus selected/i })).toBeVisible();
            await expect(page.locator('.overflow-menu')).not.toBeVisible();
        });

        test('exposes every advanced control in one View disclosure', async ({ page }) => {
            const view = page.locator('.view-disclosure summary');
            await expect(view).toBeVisible();
            await view.click();
            const menu = page.locator('.overflow-menu');
            await expect(menu).toBeVisible();
            await expect(menu.getByLabel('Layout')).toBeVisible();
            await expect(menu.getByLabel('Curves')).toBeVisible();
            await expect(menu.getByRole('slider', { name: 'Spacing' })).toBeVisible();
            await expect(menu.getByRole('slider', { name: 'Depth' })).toBeVisible();
            await expect(menu.getByLabel('Labels')).toBeVisible();
            await expect(menu.getByRole('button', { name: 'Reset View' })).toBeVisible();
            await expect(menu.getByRole('button', { name: 'Dev Tasks' })).toBeVisible();
            await expect(menu.getByRole('link', { name: /Pipeline/ })).toBeVisible();
        });

        test('closes View when focus moves to a primary field by pointer', async ({ page }) => {
            await page.locator('.view-disclosure summary').click();
            await expect(page.locator('.overflow-menu')).toBeVisible();
            await page.getByRole('searchbox', { name: 'Search', exact: true }).click();
            await expect(page.locator('.overflow-menu')).not.toBeVisible();
        });
    });
}

test.describe('Toolbar — mobile targets and overflow', () => {
    test.use({ viewport: VIEWPORTS.mobile_medium });

    test('all visible primary and disclosed controls meet the 44px target', async ({ page }) => {
        await openToolbar(page);
        for (const control of await page.locator('.toolbar input:visible, .toolbar select:visible, .toolbar button:visible, .toolbar summary:visible').all()) {
            expect((await control.boundingBox())?.height).toBeGreaterThanOrEqual(44);
        }
        await page.locator('.view-disclosure summary').click();
        for (const control of await page.locator('.overflow-menu input:visible, .overflow-menu select:visible, .overflow-menu button:visible, .overflow-menu a:visible').all()) {
            expect((await control.boundingBox())?.height).toBeGreaterThanOrEqual(44);
        }
    });

    test('Graph Stats expands inside View', async ({ page }) => {
        await openToolbar(page);
        await page.locator('.view-disclosure summary').click();
        await page.getByRole('button', { name: 'Graph stats' }).click();
        await expect(page.locator('.stats-grid')).toBeVisible();
        await expect(page.locator('.stat-value')).toHaveCount(5);
    });
});

test.describe('Toolbar — 320px no horizontal overflow', () => {
    test.use({ viewport: VIEWPORTS.mobile_small });

    test('toolbar and document fit the viewport', async ({ page }) => {
        await openToolbar(page);
        const dimensions = await page.locator('.toolbar').evaluate((element: HTMLElement) => ({
            scrollWidth: element.scrollWidth,
            offsetWidth: element.offsetWidth,
            width: element.getBoundingClientRect().width,
        }));
        expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.offsetWidth);
        expect(dimensions.width).toBeLessThanOrEqual(VIEWPORTS.mobile_small.width);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    });
});
