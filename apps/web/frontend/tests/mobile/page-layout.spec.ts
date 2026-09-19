import { test, expect } from '@playwright/test';

const MOBILE = { width: 375, height: 667 };
const DESKTOP = { width: 1280, height: 800 };

test.describe('mobile: desktop-only components hidden', () => {
    test.beforeEach(async ({ page }) => {
        await page.setViewportSize(MOBILE);
        await page.goto('/');
    });

    test('StatusBar is not in the DOM on mobile', async ({ page }) => {
        // {#if !$media.mobile} removes it entirely — not just display:none
        const statusBar = page.locator('.status-bar');
        await expect(statusBar).toHaveCount(0);
    });

    test('PresentationViewer is not in the DOM on mobile', async ({ page }) => {
        const viewer = page.locator('.presentation-viewer');
        await expect(viewer).toHaveCount(0);
    });

    test('TerminalPane is not in the DOM on mobile', async ({ page }) => {
        const terminal = page.locator('.terminal-pane');
        await expect(terminal).toHaveCount(0);
    });

    test('.main-area keeps the compact inset on mobile', async ({ page }) => {
        const paddingBottom = await page.locator('.main-area').evaluate(
            (el) => window.getComputedStyle(el).paddingBottom
        );
        expect(paddingBottom).toBe('8px');
    });

    test('.has-diegesis-panel .graph-area has margin-left: 0 on mobile', async ({ page }) => {
        // Activate a diegesis panel to trigger .has-diegesis-panel
        await page.evaluate(() => {
            document.querySelector('.app-container')?.classList.add('has-diegesis-panel');
        });
        const marginLeft = await page.locator('.graph-area').evaluate(
            (el) => window.getComputedStyle(el).marginLeft
        );
        expect(marginLeft).toBe('0px');
    });
});

test.describe('desktop: all components present', () => {
    test.beforeEach(async ({ page }) => {
        await page.setViewportSize(DESKTOP);
        await page.goto('/');
    });

    test('StatusBar is in the DOM on desktop', async ({ page }) => {
        await expect(page.locator('.status-bar')).toHaveCount(1);
    });

    test('PresentationViewer is not owned by the graph route on desktop', async ({ page }) => {
        await expect(page.locator('.presentation-viewer')).toHaveCount(0);
    });

    test('TerminalPane remains inactive without a terminal job on desktop', async ({ page }) => {
        await expect(page.locator('.terminal-pane')).toHaveCount(0);
    });
});
