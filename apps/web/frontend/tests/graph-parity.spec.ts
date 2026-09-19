import { expect, test, type Page } from '@playwright/test';
import type { Graph } from '../src/lib/api';

const graph: Graph = {
    version: 'producer-compatible-fixture',
    nodes: [
        { slug: 'alpha', title: 'Alpha', belief: 'Alpha belief', tags: [], evidence: [{ source: 'source', quote: null, url: null }] },
        { slug: 'beta', title: 'Beta', belief: 'Beta belief', tags: ['anti-pattern'], evidence: [] },
        { slug: 'gamma', title: 'Gamma', belief: 'Gamma belief', tags: [], evidence: [] },
        { slug: 'delta', title: 'Delta', belief: 'Delta belief', tags: [], evidence: [] }
    ],
    edges: [
        { source: 'alpha', target: 'beta', type: 'grounds', alias: 'grounds' },
        { source: 'beta', target: 'gamma', type: 'contradicts', alias: 'contradicts' }
    ]
};

async function graphPage(page: Page, fixture: Graph = graph, url = '/') {
    await page.route('**/api/graph', (route) => route.fulfill({ json: fixture }));
    await page.route('**/api/graph/version', (route) => route.fulfill({ json: { version: fixture.version } }));
    await page.route('**/api/diegeses', (route) => route.fulfill({ json: [] }));
    await page.goto(url);
    if (fixture.nodes[0]) {
        await expect(page.getByRole('button', { name: new RegExp(fixture.nodes[0].belief || fixture.nodes[0].title) })).toBeVisible();
    }
}

test('selects nodes, edges, clears the background, and hides labels by default', async ({ page }) => {
    await graphPage(page);
    await expect(page.locator('.edge-label')).toHaveCount(0);
    await page.getByRole('button', { name: /Alpha belief/ }).click();
    await expect(page.getByRole('button', { name: /Alpha belief/ })).toHaveAttribute('tabindex', '0');
    await page.locator('.graph-edge').first().evaluate((edge) => edge.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await expect(page.getByRole('button', { name: /Alpha belief/ })).toHaveAttribute('tabindex', '-1');
    await page.locator('.graph-background').click({ position: { x: 2, y: 2 } });
    await expect(page.getByRole('button', { name: /Alpha belief/ })).toHaveAttribute('tabindex', '-1');
});

test('a missing node detail reports an error without breaking graph interactions', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('**/api/doxai/alpha', (route) => route.fulfill({ status: 404, json: { detail: 'Not found' } }));
    await graphPage(page);
    await page.getByRole('button', { name: /Alpha belief/ }).click();
    await expect(page.getByText('Failed to load details', { exact: true })).toBeVisible();
    await page.locator('.graph-svg').focus();
    await page.keyboard.press('Escape');
    await page.getByLabel('Search').fill('delta');
    await expect(page.getByRole('button', { name: /Alpha belief/ })).toHaveClass(/is-dimmed/);
    await expect(page.getByRole('button', { name: /Delta belief/ })).not.toHaveClass(/is-dimmed/);
    expect(errors).toEqual([]);
});

test('defines resolved edge markers and previews the hovered neighborhood without changing geometry', async ({ page }) => {
    await graphPage(page);
    for (const marker of ['ink', 'rubedo', 'gold']) await expect(page.locator(`#graph-arrow-${marker}`)).toHaveCount(1);
    const edges = page.locator('.graph-edge');
    for (let index = 0; index < await edges.count(); index += 1) {
        const marker = await edges.nth(index).getAttribute('marker-end');
        expect(marker).toMatch(/^url\(#graph-arrow-(ink|rubedo|gold)\)$/);
        await expect(page.locator(marker!.slice(4, -1))).toHaveCount(1);
    }

    const beta = page.getByRole('button', { name: /Beta belief/ });
    await beta.hover();
    await expect(page.locator('.node-label-card')).toContainText('Beta belief');
    await expect(page.locator('.graph-node.is-neighbor')).toHaveCount(3);
    await expect(page.getByRole('button', { name: /Delta belief/ })).toHaveClass(/is-dimmed/);
    await expect(beta.locator('.node-hit-target')).toHaveAttribute('width', '44');
    await expect(beta.locator('.node-hit-target')).toHaveAttribute('height', '44');
    await expect(beta.locator('.defeater-mark')).not.toHaveAttribute('d', '');

    await edges.nth(1).evaluate((edge) => edge.dispatchEvent(new PointerEvent('pointerenter')));
    await expect(page.locator('.edge-endpoint-halo')).toHaveCount(2);
});

test('rebuilds a same-version scoped graph response selected through the Toolbar', async ({ page }) => {
    const scoped: Graph = { ...graph, nodes: [{ slug: 'scoped', title: 'Scoped', belief: 'Scoped belief', tags: [], evidence: [] }], edges: [] };
    await page.route('**/api/graph/scoped?**', (route) => route.fulfill({ json: scoped }));
    await page.route('**/api/graph', (route) => route.fulfill({ json: graph }));
    await page.route('**/api/graph/version', (route) => route.fulfill({ json: { version: graph.version } }));
    await page.route('**/api/diegeses', (route) => route.fulfill({ json: [{ slug: 'scope', title: 'Scope', subtitle: null, section_count: 1, walk_count: 0, walks: [] }] }));
    await page.goto('/');

    await page.getByLabel('Diegesis').selectOption('scope');

    await expect(page.getByRole('button', { name: /Scoped belief/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Alpha belief/ })).toHaveCount(0);
});

test('redraws display stores through Toolbar controls and external writes', async ({ page }) => {
    await graphPage(page);
    const firstEdgePath = await page.locator('.graph-edge').first().getAttribute('d');

    await page.getByLabel('Search').fill('delta');
    await expect(page.getByRole('button', { name: /Alpha belief/ })).toHaveClass(/is-dimmed/);
    await page.locator('.view-disclosure summary').click();
    await page.getByLabel('Labels').check();
    await expect(page.locator('.edge-label')).toHaveCount(2);
    await page.getByLabel('Curves').selectOption('taxi');
    await expect.poll(() => page.locator('.graph-edge').first().getAttribute('d')).not.toBe(firstEdgePath);

    await page.evaluate(async () => {
        const storeModule = '/src/lib/stores/graph.ts';
        const stores = await import(storeModule);
        stores.searchQuery.set('');
        stores.selectedNode.set('alpha');
        stores.selectedEdge.set({ source: 'alpha', target: 'beta' });
    });
    await expect(page.getByRole('button', { name: /Alpha belief/ })).toHaveClass(/is-selected/);
    await expect(page.locator('.graph-edge').first()).toHaveClass(/is-selected/);
});

test('ignores an out-of-order layout worker response after a newer resize request', async ({ page }) => {
    await page.addInitScript(() => {
        class ControlledWorker {
            onmessage: ((event: MessageEvent) => void) | null = null;
            onerror: ((event: Event) => void) | null = null;
            postMessage(request: any) {
                const coordinate = request.id === 1 ? 11 : 222;
                const delay = request.id === 1 ? 250 : 0;
                setTimeout(() => this.onmessage?.({ data: {
                    id: request.id,
                    positions: Object.fromEntries(request.nodes.map((node: any) => [node.id, { x: coordinate, y: coordinate }])),
                    ticks: request.id
                } } as MessageEvent), delay);
            }
            terminate() {}
        }
        class ControlledResizeObserver {
            constructor(private callback: ResizeObserverCallback) {}
            observe() { setTimeout(() => this.callback([], this as unknown as ResizeObserver), 100); }
            disconnect() {}
        }
        Object.defineProperty(window, 'Worker', { configurable: true, writable: true, value: ControlledWorker });
        Object.defineProperty(window, 'ResizeObserver', { configurable: true, writable: true, value: ControlledResizeObserver });
    });
    await graphPage(page);
    const firstNode = page.locator('.graph-node').first();
    await expect(firstNode).toHaveAttribute('transform', 'translate(222,222)', { timeout: 5000 });
    await page.waitForTimeout(300);
    await expect(firstNode).toHaveAttribute('transform', 'translate(222,222)');
});

test('uses roving node focus without trapping Tab and supports neighbor keys', async ({ page }) => {
    await graphPage(page);
    const graphCanvas = page.locator('.graph-svg');
    await graphCanvas.focus();
    await expect(graphCanvas).toHaveCSS('outline-style', 'solid');
    await expect.poll(() => graphCanvas.evaluate((element) => getComputedStyle(element).outlineColor)).not.toBe('rgba(0, 0, 0, 0)');
    await page.keyboard.press('Home');
    await expect(page.getByRole('button', { name: /Alpha belief/ })).toHaveAttribute('tabindex', '0');
    await page.keyboard.press('ArrowRight');
    await expect(page.getByRole('button', { name: /Beta belief/ })).toHaveAttribute('tabindex', '0');
    await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: /Beta belief/ })).toHaveAttribute('tabindex', '-1');
    await page.keyboard.press('Tab');
    await expect(page.getByRole('button', { name: 'Zoom in' })).toBeFocused();
});

test('offers native and keyboard camera controls without intercepting editable targets', async ({ page }) => {
    await graphPage(page);
    const viewport = page.locator('.graph-viewport');
    const initial = await viewport.getAttribute('transform');
    await page.getByRole('button', { name: 'Zoom in' }).click();
    await expect.poll(() => viewport.getAttribute('transform')).not.toBe(initial);
    await page.getByRole('button', { name: 'Zoom out' }).click();
    await page.getByRole('button', { name: 'Fit', exact: true }).click();

    const graphCanvas = page.locator('.graph-svg');
    await graphCanvas.focus();
    const fitted = await viewport.getAttribute('transform');
    await page.keyboard.press('+');
    await expect.poll(() => viewport.getAttribute('transform')).not.toBe(fitted);
    await page.keyboard.press('-');
    await page.keyboard.press('0');

    const beforeEdit = await viewport.getAttribute('transform');
    await graphCanvas.evaluate((svg) => {
        const foreign = document.createElementNS('http://www.w3.org/2000/svg', 'foreignObject');
        const input = document.createElement('input');
        input.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml');
        input.className = 'graph-editable-proof';
        foreign.append(input);
        svg.append(foreign);
        input.focus();
    });
    await page.keyboard.type('+');
    await expect(page.locator('.graph-editable-proof')).toHaveValue('+');
    await expect(viewport).toHaveAttribute('transform', beforeEdit!);
});

test('clamps a user-panned camera after resize so graph content stays reachable', async ({ page }) => {
    await graphPage(page);
    const canvas = page.locator('.graph-svg');
    const box = await canvas.boundingBox();
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
    await page.mouse.down();
    await page.mouse.move(box!.x + box!.width + 2000, box!.y + box!.height + 2000);
    await page.mouse.up();

    await page.setViewportSize({ width: 900, height: 600 });

    await expect.poll(async () => {
        const graphBox = await page.locator('.graph-container').boundingBox();
        const nodeBox = await page.locator('.graph-node').first().boundingBox();
        return !!graphBox && !!nodeBox && nodeBox.x < graphBox.x + graphBox.width && nodeBox.y < graphBox.y + graphBox.height
            && nodeBox.x + nodeBox.width > graphBox.x && nodeBox.y + nodeBox.height > graphBox.y;
    }).toBe(true);
});

test.describe('stone activation', () => {
    const stoneGraph: Graph = {
        version: 'stone-fixture',
        nodes: [{ slug: 'alpha', title: 'Alpha', belief: 'Alpha belief', tags: [], evidence: [] }],
        edges: []
    };

    async function stonePage(page: Page) {
        await page.route('**/api/theses/demo/slides/intro', (route) => route.fulfill({ json: { doxai: ['alpha'] } }));
        await graphPage(page, stoneGraph, '/?thesis=demo&slide=intro');
        await expect(page.getByRole('button', { name: /^Stone/ })).toBeVisible();
    }

    test('pointer activation returns to the presentation thesis and slide route', async ({ page }) => {
        await stonePage(page);
        await page.getByRole('button', { name: /^Stone/ }).click();
        await expect(page).toHaveURL(/\/presentations\?thesis=demo&slide=intro$/);
    });

    test('keyboard activation returns to the presentation thesis and slide route', async ({ page }) => {
        await stonePage(page);
        await page.locator('.graph-svg').focus();
        await page.keyboard.press('Home');
        await page.keyboard.press('ArrowRight');
        const selectedBeforeActivation = await page.evaluate(async () => {
            const storeModule = '/src/lib/stores/graph.ts';
            const { selectedNode } = await import(storeModule);
            let current: string | null = null;
            const unsubscribe = selectedNode.subscribe((value: string | null) => { current = value; });
            unsubscribe();
            return current;
        });
        expect(selectedBeforeActivation).toBe('alpha');
        await page.keyboard.press('Enter');
        await expect(page).toHaveURL(/\/presentations\?thesis=demo&slide=intro$/);
    });
});
