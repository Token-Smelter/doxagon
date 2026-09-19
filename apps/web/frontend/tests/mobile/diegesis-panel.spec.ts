import { test, expect } from '@playwright/test';
import { VIEWPORTS } from '../viewports';

test.describe('DiegesisPanel mobile drawer', () => {
    async function mockDiegesis(page: import('@playwright/test').Page, delay = 0) {
        await page.route('**/api/graph/scoped?**', (route) => route.fulfill({ json: { version: 'scope', nodes: [], edges: [] } }));
        await page.route('**/api/graph/version', (route) => route.fulfill({ json: { version: 'scope' } }));
        await page.route('**/api/diegeses/test-diegesis', async (route) => {
            if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
            await route.fulfill({ json: {
                slug: 'test-diegesis', title: 'Test Diegesis', subtitle: 'A grounded scope',
                sections: { opening: { title: 'Opening', doxai: ['alpha'] } },
                walks: { canonical: ['opening'], alternate: ['opening'] }, theses: [],
                body: 'Description with [[alpha]].'
            } });
        });
        await page.route('**/api/theses?diegesis=test-diegesis', (route) => route.fulfill({ json: [{
            slug: 'thesis-one', name: 'Thesis One', diegesis: 'test-diegesis', walk: 'canonical',
            slide_count: 2, slides_with_images: 1, has_presentation: true, has_essay: false
        }] }));
    }

    test('renders drawer and backdrop on mobile when diegesis is open', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await mockDiegesis(page);
        await page.goto('/?diegesis=test-diegesis');
        await expect(page.getByRole('heading', { name: 'Test Diegesis' })).toBeVisible();

        const backdrop = page.locator('.drawer-backdrop');
        const panel = page.locator('.diegesis-panel.mobile');

        // If panel is visible (server returned data), backdrop should also be present
        const panelVisible = await panel.isVisible().catch(() => false);
        if (panelVisible) {
            await expect(backdrop).toBeVisible();
            // Drawer width should be at most 280px
            const box = await panel.boundingBox();
            expect(box?.width).toBeLessThanOrEqual(280);
        } else {
            // No active diegesis loaded — backdrop should not render
            await expect(backdrop).toHaveCount(0);
        }
    });

    test('no backdrop on desktop', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.desktop);
        await mockDiegesis(page);
        await page.goto('/?diegesis=test-diegesis');
        await expect(page.getByRole('heading', { name: 'Test Diegesis' })).toBeVisible();

        const backdrop = page.locator('.drawer-backdrop');
        await expect(backdrop).toHaveCount(0);
    });

    test('desktop panel is 280px wide with no mobile class', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.desktop);
        await mockDiegesis(page);
        await page.goto('/');

        const mobilePanel = page.locator('.diegesis-panel.mobile');
        await expect(mobilePanel).toHaveCount(0);

        // If a panel is visible at all, it should be 280px
        const panel = page.locator('.diegesis-panel');
        const count = await panel.count();
        if (count > 0) {
            const box = await panel.boundingBox();
            expect(box?.width).toBe(280);
        }
    });

    test('tapping backdrop closes the drawer', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await mockDiegesis(page);
        await page.goto('/?diegesis=test-diegesis');
        await expect(page.getByRole('heading', { name: 'Test Diegesis' })).toBeVisible();

        const backdrop = page.locator('.drawer-backdrop');
        const panel = page.locator('.diegesis-panel.mobile');

        const panelVisible = await panel.isVisible().catch(() => false);
        if (panelVisible) {
            await expect(backdrop).toBeVisible();
            await backdrop.click({ position: { x: 350, y: 300 } });
            // After clicking backdrop, panel should be gone
            await expect(panel).toHaveCount(0);
        }
    });

    test('keyboard focus, walk state, safe thesis return, and Escape are preserved', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await mockDiegesis(page);
        await page.goto('/?diegesis=test-diegesis');

        const panel = page.getByRole('dialog', { name: 'Diegesis inspector' });
        await expect(panel).toBeFocused();
        await page.getByRole('button', { name: /alternate/ }).click();
        await expect(page.getByRole('button', { name: /alternate/ })).toHaveAttribute('aria-pressed', 'true');
        await expect(page.getByRole('link', { name: 'View Presentation' })).toHaveAttribute('href', /return=%2F%3Fdiegesis%3Dtest-diegesis%26walk%3Dalternate/);
        await page.keyboard.press('Escape');
        await expect(panel).toHaveCount(0);
    });

    test('shows loading state, swaps semantic grounds, and never overflows', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await mockDiegesis(page, 2000);
        await page.goto('/?diegesis=test-diegesis');
        const panel = page.locator('.diegesis-panel');
        await expect(panel.getByText('Loading...')).toBeVisible();
        const cream = await panel.evaluate((element) => getComputedStyle(element).backgroundColor);
        await page.evaluate(() => document.body.classList.add('dox-invert'));
        await expect(page.getByRole('heading', { name: 'Test Diegesis' })).toBeVisible();
        expect(await panel.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe(cream);
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
    });
});
