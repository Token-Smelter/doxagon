import type { Edge, Graph } from '$lib/api';

export interface GraphStoneContext {
    thesis: string;
    slide: string;
    doxai: string[];
}

export interface RenderNode {
    id: string;
    slug: string;
    label: string;
    belief: string;
    evidenceCount: number;
    degree: number;
    scale: number;
    defeater: boolean;
    kind: 'doxa' | 'stone';
    source?: Graph['nodes'][number];
}

export interface RenderEdge extends Edge {
    id: string;
    label: string;
    stoneEdge: boolean;
}

export interface GraphModel {
    nodes: RenderNode[];
    edges: RenderEdge[];
    outgoing: Map<string, string[]>;
    incoming: Map<string, string[]>;
    edgeById: Map<string, RenderEdge>;
}

export function edgeId(edge: Pick<Edge, 'source' | 'target'>, index = 0): string {
    return `${edge.source}→${edge.target}:${index}`;
}

export function createGraphModel(graph: Graph, stone?: GraphStoneContext | null): GraphModel {
    const degree = new Map<string, number>();
    const outgoing = new Map<string, string[]>();
    const incoming = new Map<string, string[]>();
    const nodeIds = new Set(graph.nodes.map((node) => node.slug));

    for (const edge of graph.edges) {
        if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
        degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
        degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
        outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge.target]);
        incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge.source]);
    }

    const maxDegree = Math.max(1, ...degree.values());
    const nodes: RenderNode[] = graph.nodes.map((node) => {
        const nodeDegree = degree.get(node.slug) ?? 0;
        return {
            id: node.slug,
            slug: node.slug,
            label: node.belief || node.title || node.slug,
            belief: node.belief || node.title || node.slug,
            evidenceCount: node.evidence?.length ?? 0,
            degree: nodeDegree,
            scale: 0.85 + (nodeDegree / maxDegree) * 0.5,
            defeater: node.tags.includes('anti-pattern'),
            kind: 'doxa',
            source: node
        };
    });

    const edges: RenderEdge[] = graph.edges
        .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
        .map((edge, index) => ({ ...edge, id: edgeId(edge, index), label: edge.alias || edge.type, stoneEdge: false }));

    if (stone && stone.doxai.length > 0) {
        const stoneId = `stone:${stone.thesis}`;
        nodes.push({ id: stoneId, slug: stoneId, label: 'Stone', belief: 'Stone', evidenceCount: 0, degree: stone.doxai.length, scale: 1, defeater: false, kind: 'stone' });
        for (const slug of stone.doxai.filter((slug) => nodeIds.has(slug))) {
            const id = `${slug}→${stoneId}:stone`;
            edges.push({ id, source: slug, target: stoneId, type: 'includes', label: 'included in slide', stoneEdge: true });
            outgoing.set(slug, [...(outgoing.get(slug) ?? []), stoneId]);
            incoming.set(stoneId, [...(incoming.get(stoneId) ?? []), slug]);
        }
    }

    return { nodes, edges, outgoing, incoming, edgeById: new Map(edges.map((edge) => [edge.id, edge])) };
}

export function downstream(model: GraphModel, root: string): string[] {
    const seen = new Set([root]);
    const queue = [root];
    const result: string[] = [];
    while (queue.length) {
        const current = queue.shift()!;
        for (const next of model.outgoing.get(current) ?? []) {
            if (!seen.has(next)) {
                seen.add(next);
                result.push(next);
                queue.push(next);
            }
        }
    }
    return result;
}
