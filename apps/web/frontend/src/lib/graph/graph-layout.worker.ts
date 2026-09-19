/// <reference lib="webworker" />
import { forceCenter, forceCollide, forceLink, forceManyBody, forceRadial, forceSimulation, type SimulationNodeDatum } from 'd3-force';
import { circleFallback, seededNumber, virtualCanvas, type Bounds, type LayoutRequest, type Position } from './graph-layout';

type ForceNode = SimulationNodeDatum & { id: string; degree: number; kind: 'doxa' | 'stone'; };

function initialPosition(id: string, request: LayoutRequest, canvas: Bounds): Position {
    const cached = request.positions[id];
    if (cached && Number.isFinite(cached.x) && Number.isFinite(cached.y)) return cached;
    return { x: 28 + seededNumber(`${id}:x`) * Math.max(1, canvas.width - 56), y: 28 + seededNumber(`${id}:y`) * Math.max(1, canvas.height - 56) };
}

function normalizePositions(nodes: ForceNode[], canvas: Bounds): Record<string, Position> {
    const xs = nodes.map((node) => node.x ?? 0);
    const ys = nodes.map((node) => node.y ?? 0);
    const minX = Math.min(...xs); const maxX = Math.max(...xs);
    const minY = Math.min(...ys); const maxY = Math.max(...ys);
    const extentX = Math.max(1, maxX - minX);
    const extentY = Math.max(1, maxY - minY);
    const offsetX = (canvas.width - extentX) / 2;
    const offsetY = (canvas.height - extentY) / 2;
    return Object.fromEntries(nodes.map((node) => [node.id, {
        x: offsetX + (node.x ?? minX) - minX,
        y: offsetY + (node.y ?? minY) - minY
    }]));
}

function breadthfirst(request: LayoutRequest): Record<string, Position> {
    const ids = request.nodes.map((node) => node.id).sort();
    const indegree = new Map(ids.map((id) => [id, 0]));
    const outgoing = new Map<string, string[]>();
    for (const edge of request.edges) {
        indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1);
        outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge.target]);
    }
    const levels = new Map<string, number>();
    const queue = ids.filter((id) => indegree.get(id) === 0);
    for (const id of queue) levels.set(id, 0);
    while (queue.length) {
        const current = queue.shift()!;
        for (const target of outgoing.get(current) ?? []) {
            levels.set(target, Math.max(levels.get(target) ?? 0, (levels.get(current) ?? 0) + 1));
            indegree.set(target, (indegree.get(target) ?? 1) - 1);
            if (indegree.get(target) === 0) queue.push(target);
        }
    }
    for (const id of ids) if (!levels.has(id)) levels.set(id, (levels.size % 4) + 1);
    const maxLevel = Math.max(1, ...levels.values());
    const result: Record<string, Position> = {};
    for (const [level, members] of Array.from({ length: maxLevel + 1 }, (_, level) => [level, ids.filter((id) => levels.get(id) === level)] as const)) {
        members.forEach((id, index) => {
            result[id] = { x: ((level + 1) / (maxLevel + 2)) * request.bounds.width, y: ((index + 1) / (members.length + 1)) * request.bounds.height };
        });
    }
    return result;
}

function concentric(request: LayoutRequest): Record<string, Position> {
    const ordered = [...request.nodes].sort((a, b) => b.degree - a.degree || a.id.localeCompare(b.id));
    const center = { x: request.bounds.width / 2, y: request.bounds.height / 2 };
    const result: Record<string, Position> = {};
    ordered.forEach((node, index) => {
        const ring = Math.floor(Math.sqrt(index));
        const start = ring * ring;
        const count = Math.max(1, (ring + 1) ** 2 - start);
        const angle = ((index - start) / count) * Math.PI * 2 - Math.PI / 2;
        const radius = ring * Math.max(58, request.spacing * 0.72);
        result[node.id] = { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius };
    });
    return result;
}

function force(request: LayoutRequest, initial: Record<string, Position>, canvas: Bounds): { positions: Record<string, Position>; ticks: number } {
    const nodes: ForceNode[] = request.nodes.map((node) => ({ ...node, ...initial[node.id] }));
    const simulation = forceSimulation(nodes)
        .force('link', forceLink(request.edges).id((node: any) => node.id).distance(60 + request.spacing * 0.4).strength(0.4))
        .force('charge', forceManyBody<ForceNode>().strength((node) => node.degree === 0 ? 0 : -Math.max(40, request.spacing * 0.4)))
        .force('collide', forceCollide(Math.max(34, request.spacing * 0.3)).strength(1).iterations(4))
        .force('orphans', forceRadial<ForceNode>(Math.min(canvas.width, canvas.height) * 0.43, canvas.width / 2, canvas.height / 2).strength((node) => node.degree === 0 ? 0.3 : 0))
        .force('center', forceCenter(canvas.width / 2, canvas.height / 2))
        .stop();
    const ticks = Math.min(220, Math.ceil(Math.log(simulation.alphaMin()) / Math.log(1 - simulation.alphaDecay())));
    for (let tick = 0; tick < ticks; tick += 1) simulation.tick();
    return { positions: normalizePositions(nodes, canvas), ticks };
}

self.onmessage = (event: MessageEvent<LayoutRequest>) => {
    const request = event.data;
    try {
        const canvas = virtualCanvas(request.bounds, request.nodes.length, request.spacing);
        const initial = request.layout === 'circle' ? circleFallback(request.nodes, request.bounds, request.spacing)
            : request.layout === 'breadthfirst' ? breadthfirst(request)
            : request.layout === 'concentric' ? concentric(request)
            : Object.fromEntries(request.nodes.map((node) => [node.id, initialPosition(node.id, request, canvas)]));
        const result = request.layout === 'fcose' ? force(request, initial, canvas) : { positions: initial, ticks: 0 };
        (self as DedicatedWorkerGlobalScope).postMessage({ id: request.id, ...result });
    } catch {
        (self as DedicatedWorkerGlobalScope).postMessage({ id: request.id, positions: circleFallback(request.nodes, request.bounds, request.spacing), ticks: 0 });
    }
};
