import { expect, test, type Page } from '@playwright/test';
import type { Graph } from '../src/lib/api';

test.describe.configure({ mode: 'serial' });

function fixture(nodeCount: number, edgeCount: number, connectedNodeCount = nodeCount, highEvidenceNodes: number[] = []): Graph {
    const nodes = Array.from({ length: nodeCount }, (_, index) => ({
        slug: `doxa-${index}`,
        title: `Doxa ${index}`,
        belief: `Belief ${index}`,
        tags: index % 29 === 0 ? ['anti-pattern'] : [],
        evidence: highEvidenceNodes.includes(index)
            ? Array.from({ length: 7 }, (_, evidenceIndex) => ({ source: `source-${index}-${evidenceIndex}`, quote: null, url: null }))
            : index % 11 === 0 ? [{ source: `source-${index}`, quote: null, url: null }] : []
    }));
    const edges = Array.from({ length: edgeCount }, (_, index) => ({
        source: nodes[index % connectedNodeCount].slug,
        target: nodes[(index + 1 + Math.floor(index / connectedNodeCount)) % connectedNodeCount].slug,
        type: index % 2 === 0 ? 'grounds' : 'supports',
        alias: index % 7 === 0 ? `relation-${index}` : undefined
    }));
    return { version: `fixture-${nodeCount}-${edgeCount}`, nodes, edges };
}

async function routeGraph(page: Page, graph: Graph, onGraphResponse?: () => void) {
    await page.route('**/api/graph', (route) => {
        onGraphResponse?.();
        return route.fulfill({ json: graph });
    });
    await page.route('**/api/graph/version', (route) => route.fulfill({ json: { version: graph.version } }));
    await page.route('**/api/diegeses', (route) => route.fulfill({ json: [] }));
}

function containsOnlyFiniteNumbers(value: string | null): boolean {
    if (!value) return false;
    const numbers = value.match(/-?\d+(?:\.\d+)?(?:e[+-]?\d+)?/gi)?.map(Number) ?? [];
    return numbers.length > 0 && numbers.every(Number.isFinite);
}

test('paints and fits the supported producer graph within its budget with labels disabled', async ({ page }) => {
    const supported = fixture(500, 1500);
    await page.addInitScript(() => {
        const originalJson = Response.prototype.json;
        Response.prototype.json = async function() {
            const result = await originalJson.call(this);
            if (new URL(this.url).pathname === '/api/graph') (window as any).__graphDataAt = performance.now();
            return result;
        };
    });
    await routeGraph(page, supported);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/');

    const firstNode = page.locator('.graph-node').first();
    await expect(firstNode).toBeVisible({ timeout: 5000 });
    await expect(firstNode).toHaveAttribute('aria-label', /Belief 0/);
    const position = await firstNode.getAttribute('transform');
    const fit = await page.locator('.graph-viewport').getAttribute('transform');
    expect(containsOnlyFiniteNumbers(position)).toBe(true);
    expect(containsOnlyFiniteNumbers(fit)).toBe(true);
    const paintDuration = await page.evaluate(() => performance.now() - (window as any).__graphDataAt);
    expect(paintDuration).toBeLessThanOrEqual(1200);
    await expect(page.locator('.edge-label')).toHaveCount(0);
});

test('keeps a production-like force graph deterministic with effective fitted screen separation', async ({ page }) => {
    const productionLike = fixture(649, 1076, 569);
    await routeGraph(page, productionLike);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/');

    const container = page.locator('.graph-container');
    await expect.poll(async () => Number(await container.getAttribute('data-layout-ticks'))).toBeGreaterThan(0);
    const positions = await page.locator('.graph-node').evaluateAll((nodes) => nodes.map((node) => {
        const [x, y] = node.getAttribute('transform')!.match(/-?\d+(?:\.\d+)?(?:e[+-]?\d+)?/gi)!.map(Number);
        return { x, y };
    }));
    expect(positions.every(({ x, y }) => Number.isFinite(x) && Number.isFinite(y))).toBe(true);
    expect(containsOnlyFiniteNumbers(await page.locator('.graph-viewport').getAttribute('transform'))).toBe(true);
    const connectedScreenPoints = await page.locator('.graph-node').evaluateAll((nodes) => nodes.slice(0, 569).map((node) => {
        const matrix = (node as SVGGElement).getScreenCTM()!;
        return { x: matrix.e, y: matrix.f };
    }));
    const closeNeighborCounts = connectedScreenPoints.map((point, index) => connectedScreenPoints
        .filter((other, otherIndex) => otherIndex !== index && Math.hypot(point.x - other.x, point.y - other.y) < 12).length);
    const nearCollisions = closeNeighborCounts.reduce((sum, count) => sum + count, 0) / 2;
    expect(nearCollisions).toBeLessThan(connectedScreenPoints.length * 0.35);
    expect(Math.max(...closeNeighborCounts)).toBeLessThanOrEqual(3);
    const graphBounds = await container.boundingBox();
    expect(graphBounds && connectedScreenPoints.every(({ x, y }) => x >= graphBounds.x + 24 && x <= graphBounds.x + graphBounds.width - 24 && y >= graphBounds.y + 24 && y <= graphBounds.y + graphBounds.height - 24)).toBe(true);

    const firstPositions = await page.locator('.graph-node').evaluateAll((nodes) => nodes.slice(0, 24).map((node) => node.getAttribute('transform')));
    await page.reload();
    await expect.poll(async () => Number(await page.locator('.graph-container').getAttribute('data-layout-ticks'))).toBeGreaterThan(0);
    await expect.poll(() => page.locator('.graph-node').evaluateAll((nodes) => nodes.slice(0, 24).map((node) => node.getAttribute('transform')))).toEqual(firstPositions);
});

test('progressively discloses overview nodes and collision-free anchors while interactions retain context', async ({ page }) => {
    const productionLike = fixture(649, 1076, 569, [0, 11]);
    await routeGraph(page, productionLike);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/');

    const canvas = page.locator('.graph-svg');
    await expect(canvas).toHaveAttribute('data-semantic-zoom', 'overview');
    await expect(page.locator('.graph-node')).toHaveCount(649);
    await expect(page.locator('.graph-edge')).toHaveCount(1076);
    const anchorCount = await page.locator('.anchor-label').count();
    expect(anchorCount).toBeGreaterThanOrEqual(6);
    expect(anchorCount).toBeLessThanOrEqual(18);
    const labelBoxes = await page.locator('.anchor-label').evaluateAll((labels) => labels.map((label) => {
        const box = label.getBoundingClientRect();
        return { x: box.x, y: box.y, right: box.right, bottom: box.bottom };
    }));
    expect(labelBoxes.every((box) => box.x >= 0 && box.y >= 0 && box.right <= 1440 && box.bottom <= 900)).toBe(true);
    expect(labelBoxes.every((box, index) => labelBoxes.slice(index + 1).every((other) => box.right <= other.x || other.right <= box.x || box.bottom <= other.y || other.bottom <= box.y))).toBe(true);
    await expect(page.locator('.graph-node.is-overview-orphan')).toHaveCount(80);
    expect(await page.locator('.graph-node.is-overview-secondary').count()).toBeGreaterThan(400);
    await expect(page.locator('.graph-node.is-anchor').first()).not.toHaveClass(/is-overview-secondary|is-overview-orphan/);
    expect(await page.locator('.graph-edge.is-overview-muted').count()).toBeGreaterThan(900);
    const simplified = page.getByRole('button', { name: /^Belief 11;/ });
    await expect(simplified.locator('.simple-node-mark')).toHaveAttribute('r', /^(?!0(?:\.0+)?$)/);
    await expect(simplified.locator('.node-mark')).toHaveAttribute('d', '');
    await expect(simplified.locator('.evidence-satellites > *')).toHaveCount(0);
    const simplifiedDefeater = page.getByRole('button', { name: /^Belief 29;/ });
    await expect(simplifiedDefeater.locator('.simple-node-mark')).toHaveAttribute('stroke-dasharray', '3 3');
    await expect(simplifiedDefeater.locator('.defeater-mark')).toHaveAttribute('d', '');

    const selected = page.getByRole('button', { name: /Belief 0/ });
    await selected.evaluate((node) => node.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await expect(page.locator('.node-label-card')).toHaveCount(1);
    await expect(page.locator('.node-label-card')).toContainText('Belief 0');
    await expect(selected).not.toHaveClass(/is-overview-secondary|is-overview-orphan/);
    await expect(selected.locator('.simple-node-mark')).toHaveAttribute('r', '0');
    await expect(selected.locator('.node-mark')).not.toHaveAttribute('d', '');
    await expect(selected.locator('.evidence-satellites circle')).toHaveCount(5);
    await expect(selected.locator('.evidence-overflow')).toHaveText('+2');
    const selectedLabelBox = await page.locator('.node-label-card').boundingBox();
    const anchorBoxesAfterSelection = await page.locator('.anchor-label').evaluateAll((labels) => labels.map((label) => label.getBoundingClientRect()).map(({ x, y, right, bottom }) => ({ x, y, right, bottom })));
    expect(anchorBoxesAfterSelection.every((box) => !selectedLabelBox || box.right <= selectedLabelBox.x || selectedLabelBox.x + selectedLabelBox.width <= box.x || box.bottom <= selectedLabelBox.y || selectedLabelBox.y + selectedLabelBox.height <= box.y)).toBe(true);
    const selectedContextCount = await page.locator('.graph-edge.is-neighborhood').count();
    expect(selectedContextCount).toBeGreaterThan(0);
    const hovered = page.getByRole('button', { name: /^Belief 1;/ });
    await hovered.evaluate((node) => node.dispatchEvent(new PointerEvent('pointerenter', { bubbles: true })));
    await hovered.evaluate((node) => node.dispatchEvent(new PointerEvent('pointerleave', { bubbles: true })));
    await expect.poll(() => page.locator('.graph-edge.is-neighborhood').count()).toBe(selectedContextCount);

    await page.getByLabel('Search').fill('Belief 640');
    await expect(page.getByRole('button', { name: /^Belief 640;/ })).not.toHaveClass(/is-dimmed|is-overview-orphan|is-overview-secondary/);
    const ordinaryEdge = page.locator('.graph-edge.is-overview-muted').first();
    await ordinaryEdge.evaluate((edge) => edge.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await expect(page.locator('.graph-edge.is-selected')).toHaveCount(1);
    await expect(page.locator('.graph-edge.is-selected')).not.toHaveClass(/is-overview-muted/);
    await page.getByLabel('Search').fill('');
    await selected.evaluate((node) => node.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    await expect(selected).toHaveClass(/is-selected/);
    for (let attempt = 0; attempt < 10 && await canvas.getAttribute('data-semantic-zoom') === 'overview'; attempt += 1) {
        await page.getByRole('button', { name: 'Zoom in' }).click();
        await page.waitForTimeout(180);
    }
    await expect(canvas).toHaveAttribute('data-semantic-zoom', 'detail');
    await expect(selected.locator('.evidence-satellites')).not.toHaveAttribute('display', 'none');
    await expect(simplified.locator('.simple-node-mark')).toHaveAttribute('r', '0');
    await expect(simplified.locator('.node-mark')).not.toHaveAttribute('d', '');
    await expect(simplified.locator('.evidence-satellites circle')).toHaveCount(5);
    await expect(simplified.locator('.evidence-overflow')).toHaveText('+2');
});

test('same-tier zoom bursts and controls transform without semantic renders', async ({ page }) => {
    await routeGraph(page, fixture(500, 1500));
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/');
    await expect.poll(async () => Number(await page.locator('.graph-container').getAttribute('data-layout-ticks'))).toBeGreaterThan(0);
    const canvas = page.locator('.graph-svg');
    await expect(canvas).toHaveAttribute('data-semantic-zoom', 'overview');
    await page.waitForTimeout(250);
    const initialRenderCount = await canvas.getAttribute('data-render-count');
    const initialAnchorHeights = await page.locator('.anchor-label').evaluateAll((labels) => labels.map((label) => label.getBoundingClientRect().height));
    const viewport = page.locator('.graph-viewport');
    const transformBeforeBurst = await viewport.getAttribute('transform');
    const canvasBox = await canvas.boundingBox();
    await page.mouse.move(canvasBox!.x + canvasBox!.width / 2, canvasBox!.y + canvasBox!.height / 2);
    for (let index = 0; index < 20; index += 1) await page.mouse.wheel(0, -1);
    await expect.poll(() => viewport.getAttribute('transform')).not.toBe(transformBeforeBurst);

    for (let index = 0; index < 2; index += 1) {
        await page.getByRole('button', { name: 'Zoom out' }).click();
        await page.waitForTimeout(200);
        await page.getByRole('button', { name: 'Zoom in' }).click();
        await page.waitForTimeout(200);
    }

    await expect(canvas).toHaveAttribute('data-semantic-zoom', 'overview');
    await expect(canvas).toHaveAttribute('data-render-count', initialRenderCount!);
    const settledAnchorHeights = await page.locator('.anchor-label').evaluateAll((labels) => labels.map((label) => label.getBoundingClientRect().height));
    expect(settledAnchorHeights).toHaveLength(initialAnchorHeights.length);
    expect(settledAnchorHeights.every((height, index) => Math.abs(height - initialAnchorHeights[index]) < 1)).toBe(true);
});

test('recovers a hidden zero-bounds 2000-node/6000-edge producer graph within stress limits', async ({ page }) => {
    const stress = fixture(2000, 6000);
    await routeGraph(page, stress);
    await page.addInitScript(() => {
        document.addEventListener('DOMContentLoaded', () => {
            const style = document.createElement('style');
            style.id = 'initially-hidden-graph';
            style.textContent = '.graph-container { display: none !important; }';
            document.head.append(style);
        }, { once: true });
    });
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/');

    const container = page.locator('.graph-container');
    await expect(container).toBeHidden();
    await page.locator('#initially-hidden-graph').evaluate((style) => style.remove());
    await expect(container).toBeVisible();
    await expect(page.getByRole('status')).toHaveText('Large graph · 2,000 nodes · labels off');
    await expect(container).toHaveAttribute('data-layout-complete', 'true', { timeout: 10000 });

    await expect(page.locator('.graph-node')).toHaveCount(2000);
    await expect(page.locator('.graph-edge')).toHaveCount(6000);
    await expect(page.locator('.edge-label')).toHaveCount(0);
    await expect(page.locator('filter')).toHaveCount(0);

    const positionsAreFinite = await page.locator('.graph-node').evaluateAll((nodes) => nodes.every((node) => {
        const values = node.getAttribute('transform')?.match(/-?\d+(?:\.\d+)?(?:e[+-]?\d+)?/gi)?.map(Number) ?? [];
        return values.length === 2 && values.every(Number.isFinite);
    }));
    expect(positionsAreFinite).toBe(true);
    expect(containsOnlyFiniteNumbers(await page.locator('.graph-viewport').getAttribute('transform'))).toBe(true);

    const ticks = Number(await container.getAttribute('data-layout-ticks'));
    expect(Number.isInteger(ticks)).toBe(true);
    expect(ticks).toBeGreaterThanOrEqual(0);
    expect(ticks).toBeLessThanOrEqual(300);

    const selectionDuration = await page.locator('.graph-node').first().evaluate((node) => {
        const started = performance.now();
        node.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        return performance.now() - started;
    });
    expect(selectionDuration).toBeLessThanOrEqual(50);
    await expect(page.locator('.graph-node').first()).toHaveAttribute('tabindex', '0');
});
