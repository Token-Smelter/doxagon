import { expect, test, type Page } from '@playwright/test';
import { VIEWPORTS } from './viewports';

test.describe.configure({ mode: 'serial' });

const graph = {
    version: 'token-shell-producer-fixture',
    nodes: [
        { slug: 'alpha', title: 'Alpha', belief: 'Alpha belief', tags: [], evidence: [] },
        { slug: 'beta', title: 'Beta', belief: 'Beta belief', tags: [], evidence: [{ source: 'Source', quote: null, url: null }] },
    ],
    edges: [{ source: 'alpha', target: 'beta', type: 'grounds', alias: 'supports' }],
};

async function openShell(page: Page, viewport: { width: number; height: number } = VIEWPORTS.desktop) {
    await page.addInitScript(() => localStorage.setItem('doxagon-ground', 'cream'));
    await page.setViewportSize(viewport);
    await page.route('**/api/graph', (route) => route.fulfill({ json: graph }));
    await page.route('**/api/graph/version', (route) => route.fulfill({ json: { version: graph.version } }));
    await page.route('**/api/diegeses', (route) => route.fulfill({
        json: [{ slug: 'scope', title: 'Scope', subtitle: null, section_count: 1, walk_count: 0, walks: [] }],
    }));
    await page.route('**/api/graph/scoped?**', (route) => route.fulfill({ json: { ...graph, nodes: [graph.nodes[1]], edges: [] } }));
    await page.goto('/');
    await expect(page.locator('.toolbar')).toBeVisible();
}

async function assertNoDocumentOverflow(page: Page) {
    await expect.poll(() => page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    )).toBe(true);
}

test('cream and nigredo resolve semantic chrome while Terminal stays nigredo', async ({ page }) => {
    await openShell(page);
    const toolbar = page.locator('.toolbar');
    const frameSurface = () => page.locator('.workspace-header').evaluate((element) => getComputedStyle(element).backgroundColor);
    await expect.poll(async () => toolbar.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe(await frameSurface());

    await page.evaluate(async () => {
        const storeModule = '/src/lib/stores/terminal.ts';
        const stores = await import(storeModule);
        stores.terminalJobs.set(new Map([['proof', {
            id: 'proof', title: 'Proof', output: ['[STATUS] Running'], status: 'running', eventSource: null,
        }]]));
        stores.activeJobId.set('proof');
        stores.terminalOpen.set(true);
    });
    const terminal = page.locator('.terminal-pane');
    await expect(terminal).toContainText('Terminal · running');
    const terminalGround = await terminal.evaluate((element) => getComputedStyle(element).backgroundColor);

    await page.getByRole('button', { name: 'Use nigredo ground' }).click();
    await expect(page.locator('body')).toHaveClass(/dox-invert/);
    await expect.poll(async () => toolbar.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe(await frameSurface());
    await expect(terminal).toHaveCSS('background-color', terminalGround);
});

test('D3 Toolbar controls preserve scope, search, labels, curves, and layout behavior', async ({ page }) => {
    await openShell(page);
    await expect(page.getByRole('button', { name: /Alpha belief/ })).toBeVisible({ timeout: 10_000 });
    await page.getByLabel('Search').fill('beta');
    await expect(page.getByRole('button', { name: /Alpha belief/ })).toHaveClass(/is-dimmed/);
    await page.locator('.view-disclosure summary').click();
    await page.getByLabel('Labels').check();
    await expect(page.locator('.edge-label')).toContainText('supports');
    await page.getByLabel('Curves').selectOption('straight');
    await page.getByLabel('Layout').selectOption('circle');
    await page.getByLabel('Diegesis').selectOption('scope');
    await expect(page.getByRole('button', { name: /Beta belief/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Alpha belief/ })).toHaveCount(0);
});

test('Dev Tasks dialog traps focus, closes with Escape, and restores its invoker', async ({ page }) => {
    await openShell(page);
    await page.locator('.view-disclosure summary').click();
    const invoker = page.getByRole('button', { name: 'Dev Tasks' });
    await invoker.focus();
    await page.keyboard.press('Enter');
    const dialog = page.getByRole('dialog', { name: 'Dev Tasks' });
    await expect(dialog).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.getByRole('button', { name: 'Close Dev Tasks' })).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.getByPlaceholder(/Describe a change/)).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(invoker).toBeFocused();
});

test('mobile controls meet 44px targets and neither declared ground overflows', async ({ page }) => {
    await openShell(page, VIEWPORTS.mobile_medium);
    await assertNoDocumentOverflow(page);

    for (const control of await page.locator('.toolbar button:visible, .toolbar input:visible, .toolbar select:visible').all()) {
        const box = await control.boundingBox();
        expect(box?.height).toBeGreaterThanOrEqual(44);
    }

    await page.locator('.view-disclosure summary').click();
    for (const control of await page.locator('.overflow-menu button:visible, .overflow-menu a:visible, .overflow-menu select:visible').all()) {
        const box = await control.boundingBox();
        expect(box?.height).toBeGreaterThanOrEqual(44);
    }

    await page.getByRole('button', { name: 'Use nigredo ground' }).click();
    await assertNoDocumentOverflow(page);
});

test('cream and nigredo control text meets WCAG AA contrast', async ({ page }) => {
    await openShell(page);
    const contrast = (selector: string) => page.locator(selector).first().evaluate((element) => {
        const parse = (value: string) => value.match(/[\d.]+/g)!.slice(0, 3).map(Number);
        const luminance = (rgb: number[]) => {
            const linear = rgb.map((channel) => {
                const value = channel / 255;
                return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
            });
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
        };
        const style = getComputedStyle(element);
        const foreground = luminance(parse(style.color));
        const background = luminance(parse(style.backgroundColor));
        return (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
    });

    for (const groundToggle of ['Use nigredo ground', 'Use cream ground']) {
        for (const selector of ['.toolbar input[type="search"]', '.toolbar button', '.status-bar']) {
            expect(await contrast(selector)).toBeGreaterThanOrEqual(4.5);
        }
        await page.getByRole('button', { name: groundToggle }).click();
    }
});

test('reduced motion removes platform control transitions', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await openShell(page);
    await page.locator('.view-disclosure summary').click();
    await expect(page.getByRole('button', { name: 'Reset View' })).toHaveCSS('transition-duration', '0s');
    await page.getByRole('button', { name: 'Dev Tasks' }).click();
    await expect(page.getByRole('dialog', { name: 'Dev Tasks' })).toHaveCSS('transition-duration', '0s');
});

test('attaches required token shell screenshots', async ({ page }, testInfo) => {
    const capture = async (name: string) => {
        const path = testInfo.outputPath(name);
        await page.screenshot({ path, fullPage: true });
        await testInfo.attach(name, { path, contentType: 'image/png' });
    };

    await openShell(page, VIEWPORTS.desktop);
    await capture('token-shell-cream-1280x800.png');
    await page.getByRole('button', { name: 'Use nigredo ground' }).click();
    await capture('token-shell-nigredo-1280x800.png');
    await page.setViewportSize(VIEWPORTS.mobile_medium);
    await page.getByRole('button', { name: 'Use cream ground' }).click();
    await assertNoDocumentOverflow(page);
    await capture('token-shell-cream-375x667.png');
});
