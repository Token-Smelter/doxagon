import type { LayoutType } from '$lib/stores/graph';
import type { GraphModel } from './graph-model';

export interface Position { x: number; y: number; }
export interface Bounds { width: number; height: number; }
export interface LayoutRequest {
    id: number;
    layout: LayoutType;
    spacing: number;
    bounds: Bounds;
    nodes: Array<{ id: string; degree: number; kind: 'doxa' | 'stone'; }>;
    edges: Array<{ source: string; target: string; }>;
    positions: Record<string, Position>;
}
export interface LayoutResult { id: number; positions: Record<string, Position>; ticks: number; }

export function hasUsableBounds(bounds: Bounds | null | undefined): bounds is Bounds {
    return !!bounds && Number.isFinite(bounds.width) && Number.isFinite(bounds.height) && bounds.width >= 1 && bounds.height >= 1;
}

export function seededNumber(input: string): number {
    let value = 2166136261;
    for (let index = 0; index < input.length; index += 1) value = Math.imul(value ^ input.charCodeAt(index), 16777619);
    return (value >>> 0) / 4294967296;
}

export function virtualCanvas(bounds: Bounds, nodeCount: number, spacing: number): Bounds {
    const aspect = Math.max(0.5, Math.min(2, bounds.width / Math.max(1, bounds.height)));
    const nodeStride = Math.max(30, spacing * 0.55);
    const area = Math.max(bounds.width * bounds.height, Math.max(1, nodeCount) * nodeStride * nodeStride);
    return {
        width: Math.max(bounds.width, Math.sqrt(area * aspect)),
        height: Math.max(bounds.height, Math.sqrt(area / aspect))
    };
}

export function circleFallback(nodes: LayoutRequest['nodes'], bounds: Bounds, spacing: number): Record<string, Position> {
    const ordered = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
    const canvas = virtualCanvas(bounds, ordered.length, spacing);
    const radius = Math.max(36, Math.min(canvas.width, canvas.height) * 0.42);
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    return Object.fromEntries(ordered.map((node, index) => {
        const angle = (Math.PI * 2 * index) / Math.max(1, ordered.length) - Math.PI / 2;
        return [node.id, { x: centerX + Math.cos(angle) * radius, y: centerY + Math.sin(angle) * radius }];
    }));
}

export function finitePositions(positions: Record<string, Position>, nodes: LayoutRequest['nodes']): boolean {
    return nodes.every(({ id }) => Number.isFinite(positions[id]?.x) && Number.isFinite(positions[id]?.y));
}

export class GraphLayoutController {
    private worker: Worker | null = null;
    private nextId = 0;
    private activeId = 0;
    private pending: { id: number; resolve: (result: LayoutResult) => void; reject: (reason: Error) => void; timeout: ReturnType<typeof setTimeout> } | null = null;

    constructor() {
        if (typeof Worker !== 'undefined') {
            this.worker = new Worker(new URL('./graph-layout.worker.ts', import.meta.url), { type: 'module' });
            this.worker.onmessage = (event: MessageEvent<LayoutResult>) => this.complete(event.data);
            this.worker.onerror = () => this.failActive();
        }
    }

    request(model: GraphModel, layout: LayoutType, spacing: number, bounds: Bounds, cached: Map<string, Position>): Promise<LayoutResult> {
        const id = ++this.nextId;
        this.cancelPending('Graph layout request superseded');
        this.activeId = id;
        const request: LayoutRequest = {
            id, layout, spacing, bounds,
            nodes: model.nodes.map(({ id: nodeId, degree, kind }) => ({ id: nodeId, degree, kind })),
            edges: model.edges.map(({ source, target }) => ({ source, target })),
            positions: Object.fromEntries(cached)
        };
        if (!this.worker) return Promise.resolve({ id, positions: circleFallback(request.nodes, bounds, spacing), ticks: 0 });
        return new Promise((resolve, reject) => {
            const timeout = setTimeout(() => {
                if (!this.pending || this.pending.id !== id) return;
                this.pending = null;
                resolve({ id, positions: circleFallback(request.nodes, bounds, spacing), ticks: 0 });
            }, 1500);
            this.pending = { id, resolve, reject, timeout };
            this.worker!.postMessage(request);
        });
    }

    private cancelPending(reason: string) {
        if (!this.pending) return;
        clearTimeout(this.pending.timeout);
        const pending = this.pending;
        this.pending = null;
        pending.reject(new Error(reason));
    }

    private complete(result: LayoutResult) {
        if (!this.pending || result.id !== this.activeId || result.id !== this.pending.id) return;
        const pending = this.pending;
        this.pending = null;
        clearTimeout(pending.timeout);
        pending.resolve(result);
    }

    private failActive() {
        if (!this.pending || this.pending.id !== this.activeId) return;
        const pending = this.pending;
        this.pending = null;
        clearTimeout(pending.timeout);
        pending.reject(new Error('Graph layout worker failed'));
    }

    destroy() {
        this.cancelPending('Graph layout controller destroyed');
        this.worker?.terminate();
        this.worker = null;
    }
}
