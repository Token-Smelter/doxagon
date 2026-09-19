import { test, expect } from '@playwright/test';
import { VIEWPORTS } from '../viewports';

test.describe('media store responsive detection', () => {
    test('reports mobile=true at 375px', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await page.goto('/');
        const container = page.locator('.app-container');
        await expect(container).toHaveAttribute('data-mobile', 'true');
    });

    test('reports mobile=false at 1280px', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.desktop);
        await page.goto('/');
        const container = page.locator('.app-container');
        await expect(container).not.toHaveAttribute('data-mobile');
    });
});
