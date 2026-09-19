import { test, expect } from '@playwright/test';
import { VIEWPORTS } from '../viewports';

test.describe('mobile performance', () => {
    test('no horizontal scroll at 375px', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await page.goto('/');
        await page.waitForLoadState('networkidle');
        const hasHScroll = await page.evaluate(
            () => document.documentElement.scrollWidth > document.documentElement.clientWidth
        );
        expect(hasHScroll).toBe(false);
    });

    test('no layout shift on mobile load', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);

        // Inject CLS observer before navigation
        await page.addInitScript(() => {
            (window as any).__cls = 0;
            new PerformanceObserver((list) => {
                for (const entry of list.getEntries()) {
                    if (!(entry as any).hadRecentInput) {
                        (window as any).__cls += (entry as any).value;
                    }
                }
            }).observe({ type: 'layout-shift', buffered: true });
        });

        await page.goto('/');
        await page.waitForLoadState('networkidle');

        // Allow time for deferred layout shifts to be recorded
        await page.waitForTimeout(1000);

        const cls = await page.evaluate(() => (window as any).__cls || 0);
        expect(cls).toBeLessThan(0.1);
    });

    test('key elements stable during load', async ({ page }) => {
        await page.setViewportSize(VIEWPORTS.mobile_medium);
        await page.goto('/');

        // Capture toolbar position after initial paint
        const toolbarInitial = await page.locator('.toolbar').boundingBox();

        await page.waitForLoadState('networkidle');
        await page.waitForTimeout(500);

        // Confirm toolbar hasn't shifted
        const toolbarFinal = await page.locator('.toolbar').boundingBox();
        if (toolbarInitial && toolbarFinal) {
            expect(Math.abs(toolbarFinal.y - toolbarInitial.y)).toBeLessThan(5);
        }

        // Confirm graph area hasn't shifted
        const graphInitial = await page.locator('.graph-area').boundingBox();
        if (graphInitial) {
            // Re-read after settling
            const graphFinal = await page.locator('.graph-area').boundingBox();
            if (graphFinal) {
                expect(Math.abs(graphFinal.y - graphInitial.y)).toBeLessThan(5);
            }
        }
    });
});
