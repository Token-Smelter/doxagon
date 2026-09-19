import { drag } from 'd3-drag';
import { select, type Selection } from 'd3-selection';
import { zoom, zoomIdentity, type ZoomTransform } from 'd3-zoom';
import type { CurveStyle } from '$lib/stores/graph';
import type { GraphModel, RenderEdge, RenderNode } from './graph-model';
import type { Position } from './graph-layout';
import { accessibleNodeLabel, blotPath, defeaterPath, edgePath, edgeSemantics, satellitePositions } from './graph-semantics';

export interface RendererState {
    selectedNode: string | null;
    focusedNode: string | null;
    selectedEdge: { source: string; target: string } | null;
    hoveredNode: string | null;
    hoveredEdge: string | null;
    previewedNode: string | null;
    impact: Set<string>;
    search: string;
    showLabels: boolean;
    curve: CurveStyle;
}

export interface RendererCallbacks {
    selectNode: (node: RenderNode) => void;
    selectEdge: (edge: RenderEdge) => void;
    clear: () => void;
    hoverNode: (id: string | null) => void;
    hoverEdge: (id: string | null) => void;
    moveNode: (id: string, position: Position) => void;
    cameraChanged: () => void;
    zoomChanged: () => void;
}

export class GraphRenderer {
    private svg: Selection<SVGSVGElement, unknown, null, undefined>;
    private viewport: Selection<SVGGElement, unknown, null, undefined>;
    private edges: Selection<SVGGElement, unknown, null, undefined>;
    private labels: Selection<SVGGElement, unknown, null, undefined>;
    private nodes: Selection<SVGGElement, unknown, null, undefined>;
    private transform: ZoomTransform = zoomIdentity;
    private zoomBehavior;
    private positions: Record<string, Position> = {};
    private model: GraphModel | null = null;
    private renderCount = 0;

    constructor(element: SVGSVGElement, private callbacks: RendererCallbacks) {
        this.svg = select(element);
        this.svg.attr('role', 'group').attr('aria-label', 'Knowledge graph').attr('tabindex', 0);
        const defs = this.svg.append('defs');
        ([
            ['ink', 'var(--dox-text-primary)'],
            ['rubedo', 'var(--dox-brand-rubedo)'],
            ['gold', 'var(--dox-brand-gold)']
        ] as const).forEach(([name, color]) => {
            defs.append('marker').attr('id', `graph-arrow-${name}`).attr('viewBox', '0 -5 10 10')
                .attr('refX', 9).attr('refY', 0).attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
                .append('path').attr('d', 'M 0,-5 L 10,0 L 0,5 Z').attr('fill', color);
        });
        this.svg.append('rect').attr('class', 'graph-background').attr('width', '100%').attr('height', '100%').attr('fill', 'transparent')
            .on('click', () => this.callbacks.clear());
        this.viewport = this.svg.append('g').attr('class', 'graph-viewport');
        this.edges = this.viewport.append('g').attr('class', 'graph-edges');
        this.labels = this.viewport.append('g').attr('class', 'graph-labels');
        this.nodes = this.viewport.append('g').attr('class', 'graph-nodes');
        this.zoomBehavior = zoom<SVGSVGElement, unknown>().scaleExtent([0.18, 3]).filter((event) => !event.button || event.type === 'wheel')
            .on('zoom', (event) => {
                const previousOverview = this.isOverview();
                this.transform = event.transform;
                this.viewport.attr('transform', this.transform.toString());
                const overview = this.isOverview();
                this.svg.attr('data-semantic-zoom', overview ? 'overview' : 'detail').attr('data-zoom', this.transform.k);
                this.refreshScreenLabels();
                if (overview !== previousOverview) this.callbacks.zoomChanged();
                if (event.sourceEvent) this.callbacks.cameraChanged();
            });
        this.svg.call(this.zoomBehavior as any);
    }

    render(model: GraphModel, positions: Record<string, Position>, state: RendererState) {
        this.model = model;
        this.positions = positions;
        this.svg.attr('data-render-count', ++this.renderCount);
        const query = state.search.trim().toLowerCase();
        const nodeMatches = (node: RenderNode) => !query || node.label.toLowerCase().includes(query) || node.belief.toLowerCase().includes(query) || node.slug.toLowerCase().includes(query);
        const overview = this.isOverview();
        this.svg.attr('data-semantic-zoom', overview ? 'overview' : 'detail').attr('data-zoom', this.transform.k);
        const anchorLimit = Math.min(18, Math.max(6, Math.ceil(Math.sqrt(model.nodes.length) / 2)));
        const importanceRanked = [...model.nodes]
            .sort((a, b) => (b.kind === 'stone' ? 1 : 0) - (a.kind === 'stone' ? 1 : 0) || b.degree - a.degree || a.id.localeCompare(b.id));
        const roots = new Set([state.selectedNode, state.focusedNode, state.hoveredNode, state.previewedNode].filter((id): id is string => !!id));
        const selectedEdge = model.edges.find((edge) => state.selectedEdge?.source === edge.source && state.selectedEdge?.target === edge.target);
        const hoveredEdge = state.hoveredEdge ? model.edgeById.get(state.hoveredEdge) : null;
        for (const edge of [selectedEdge, hoveredEdge]) if (edge) { roots.add(edge.source); roots.add(edge.target); }
        const neighborhood = new Set(roots);
        const neighborhoodEdges = new Set<string>();
        for (const edge of model.edges) {
            if (roots.has(edge.source) || roots.has(edge.target)) {
                neighborhood.add(edge.source);
                neighborhood.add(edge.target);
                neighborhoodEdges.add(edge.id);
            }
        }
        const disclosedNodes = new Set(neighborhood);
        for (const id of state.impact) disclosedNodes.add(id);
        if (query) for (const node of model.nodes) if (nodeMatches(node)) disclosedNodes.add(node.id);
        const fullLabelId = [state.hoveredNode, state.focusedNode, state.selectedNode, state.previewedNode]
            .find((id): id is string => !!id && model.nodes.some((node) => node.id === id)) ?? null;
        const labelScale = 1 / Math.max(0.18, this.transform.k);
        const svgNode = this.svg.node();
        const viewportWidth = svgNode?.clientWidth ?? 0;
        const viewportHeight = svgNode?.clientHeight ?? 0;
        const screenPoint = (id: string) => {
            const position = positions[id] ?? { x: 0, y: 0 };
            return { x: position.x * this.transform.k + this.transform.x, y: position.y * this.transform.k + this.transform.y };
        };
        const labelWidth = (node: RenderNode) => Math.min(236, Math.max(76, Math.min(32, node.label.length) * 6.5 + 14));
        type LabelPlacement = { node: RenderNode; x: number; y: number; width: number; };
        const occupied: Array<{ x: number; y: number; width: number; height: number }> = [];
        if (fullLabelId) {
            const node = model.nodes.find((candidate) => candidate.id === fullLabelId)!;
            const point = screenPoint(node.id);
            occupied.push({ x: point.x + 28, y: point.y - 32, width: Math.min(360, Math.max(120, node.label.length * 7 + 16)), height: 26 });
        }
        const overlaps = (box: { x: number; y: number; width: number; height: number }) => occupied.some((other) => box.x < other.x + other.width + 8 && box.x + box.width + 8 > other.x && box.y < other.y + other.height + 6 && box.y + box.height + 6 > other.y);
        const anchorPlacements: LabelPlacement[] = [];
        for (const node of importanceRanked.slice(0, anchorLimit * 6)) {
            if (roots.has(node.id)) continue;
            const point = screenPoint(node.id);
            const width = labelWidth(node);
            const x = point.x + 18 + width <= viewportWidth - 8 ? point.x + 18 : point.x - width - 18;
            const y = Math.max(8, Math.min(viewportHeight - 30, point.y - 14));
            const box = { x, y, width, height: 22 };
            if (x < 8 || x + width > viewportWidth - 8 || overlaps(box)) continue;
            occupied.push(box);
            anchorPlacements.push({ node, x, y, width });
            if (anchorPlacements.length === anchorLimit) break;
        }
        const anchors = new Set(anchorPlacements.map(({ node }) => node.id));
        const nodeById = new Map(model.nodes.map((node) => [node.id, node]));
        const nodeDegree = new Map(model.nodes.map((node) => [node.id, node.degree]));
        const backboneEdges = new Set([...model.edges]
            .sort((a, b) => {
                const score = (edge: RenderEdge) => Number(edge.stoneEdge) * 100000 + (nodeDegree.get(edge.source) ?? 0) + (nodeDegree.get(edge.target) ?? 0);
                return score(b) - score(a) || a.id.localeCompare(b.id);
            })
            .slice(0, anchorLimit * 3).map((edge) => edge.id));
        const edgeSelection = this.edges.selectAll<SVGPathElement, RenderEdge>('path.graph-edge').data(model.edges, (edge) => edge.id).join(
            (enter) => enter.append('path').attr('class', 'graph-edge').attr('fill', 'none'),
            (update) => update,
            (exit) => exit.remove()
        );
        edgeSelection
            .attr('d', (edge) => edgePath(positions[edge.source] ?? { x: 0, y: 0 }, positions[edge.target] ?? { x: 0, y: 0 }, state.curve))
            .attr('stroke', (edge) => edgeSemantics(edge).stroke)
            .attr('stroke-width', (edge) => state.hoveredEdge === edge.id || neighborhoodEdges.has(edge.id) ? edgeSemantics(edge).width + 1.5 : edgeSemantics(edge).width)
            .attr('stroke-dasharray', (edge) => edgeSemantics(edge).dash)
            .attr('marker-end', (edge) => `url(#graph-arrow-${edgeSemantics(edge).marker})`)
            .classed('is-selected', (edge) => state.selectedEdge?.source === edge.source && state.selectedEdge?.target === edge.target)
            .classed('is-neighborhood', (edge) => neighborhoodEdges.has(edge.id))
            .classed('is-backbone', (edge) => backboneEdges.has(edge.id))
            .classed('is-overview-muted', (edge) => overview && !edge.stoneEdge && !backboneEdges.has(edge.id) && !neighborhoodEdges.has(edge.id) && !disclosedNodes.has(edge.source) && !disclosedNodes.has(edge.target))
            .classed('is-dimmed', (edge) => ((!query ? false : !nodeMatches(nodeById.get(edge.source)!) && !nodeMatches(nodeById.get(edge.target)!)) || (roots.size > 0 && !neighborhoodEdges.has(edge.id))) && !neighborhoodEdges.has(edge.id))
            .on('click', (event, edge) => { event.stopPropagation(); this.callbacks.selectEdge(edge); })
            .on('pointerenter', (_, edge) => this.callbacks.hoverEdge(edge.id))
            .on('pointerleave', () => this.callbacks.hoverEdge(null));

        const nodeSelection = this.nodes.selectAll<SVGGElement, RenderNode>('g.graph-node').data(model.nodes, (node) => node.id).join(
            (enter) => {
                const group = enter.append('g').attr('class', 'graph-node').attr('role', 'button');
                group.append('rect').attr('class', 'node-hit-target').attr('x', -22).attr('y', -22).attr('width', 44).attr('height', 44).attr('fill', 'transparent');
                group.append('circle').attr('class', 'simple-node-mark');
                group.append('path').attr('class', 'node-mark');
                group.append('path').attr('class', 'defeater-mark').attr('fill', 'none');
                group.append('g').attr('class', 'evidence-satellites').attr('aria-hidden', 'true');
                return group;
            },
            (update) => update,
            (exit) => exit.remove()
        );
        nodeSelection
            .attr('transform', (node) => `translate(${positions[node.id]?.x ?? 0},${positions[node.id]?.y ?? 0})`)
            .attr('aria-label', accessibleNodeLabel)
            .attr('tabindex', (node) => state.focusedNode === node.id || (!state.focusedNode && state.selectedNode === node.id) ? 0 : -1)
            .classed('is-selected', (node) => state.selectedNode === node.id)
            .classed('is-hovered', (node) => state.hoveredNode === node.id)
            .classed('is-anchor', (node) => anchors.has(node.id))
            .classed('is-neighbor', (node) => roots.size > 0 && neighborhood.has(node.id))
            .classed('is-impact', (node) => state.impact.has(node.id))
            .classed('is-overview-orphan', (node) => overview && node.degree === 0 && !disclosedNodes.has(node.id))
            .classed('is-overview-secondary', (node) => overview && node.degree > 0 && !anchors.has(node.id) && !disclosedNodes.has(node.id))
            .classed('is-dimmed', (node) => (!nodeMatches(node) || (roots.size > 0 && !neighborhood.has(node.id))) && !disclosedNodes.has(node.id))
            .on('click', (event, node) => { event.stopPropagation(); this.callbacks.selectNode(node); })
            .on('pointerenter', (_, node) => this.callbacks.hoverNode(node.id))
            .on('pointerleave', () => this.callbacks.hoverNode(null));
        const isSimplified = (node: RenderNode) => overview && node.kind === 'doxa' && !disclosedNodes.has(node.id);
        nodeSelection.select<SVGCircleElement>('circle.simple-node-mark')
            .attr('r', (node) => isSimplified(node) ? Math.min(18, 7 + (node.scale - 0.85) * 10 + Math.min(4, node.evidenceCount) * 0.75) : 0)
            .attr('fill', (node) => node.defeater ? 'var(--dox-ground)' : 'var(--dox-text-primary)')
            .attr('fill-opacity', (node) => Math.min(1, 0.4 + node.evidenceCount * 0.12))
            .attr('stroke', 'var(--dox-text-primary)')
            .attr('stroke-width', (node) => node.defeater ? 2.5 : 1)
            .attr('stroke-dasharray', (node) => node.defeater ? '3 3' : null);
        nodeSelection.select<SVGPathElement>('path.node-mark').attr('d', (node) => isSimplified(node) ? '' : blotPath(node)).attr('fill', (node) => node.kind === 'stone' || node.defeater ? 'var(--dox-ground)' : 'var(--dox-text-primary)').attr('fill-opacity', (node) => node.kind === 'stone' || node.defeater ? 1 : Math.min(1, 0.4 + node.evidenceCount * 0.12)).attr('stroke', (node) => node.kind === 'stone' ? 'var(--dox-brand-gold)' : 'var(--dox-text-primary)');
        nodeSelection.select<SVGPathElement>('path.defeater-mark').attr('d', (node) => node.defeater && !isSimplified(node) ? defeaterPath() : '').attr('stroke', 'var(--dox-brand-rubedo)').attr('stroke-width', 2.5).attr('stroke-dasharray', (node) => node.defeater ? '3 3' : null);
        nodeSelection.each(function(node) {
            const satellites = select(this).select<SVGGElement>('g.evidence-satellites');
            const simplified = isSimplified(node);
            satellites.attr('display', simplified ? 'none' : null);
            satellites.selectAll<SVGCircleElement, { x: number; y: number }>('circle').data(simplified ? [] : satellitePositions(node)).join('circle').attr('r', 3).attr('cx', (point) => point.x).attr('cy', (point) => point.y).attr('fill', 'var(--dox-ground)').attr('stroke', 'var(--dox-text-primary)').attr('stroke-width', 1.5).attr('pointer-events', 'none');
            satellites.selectAll<SVGTextElement, RenderNode>('text.evidence-overflow').data(!simplified && node.evidenceCount > 5 ? [node] : []).join('text').attr('class', 'evidence-overflow').attr('x', 20).attr('y', 25).text((value) => `+${value.evidenceCount - 5}`);
        });
        nodeSelection.call(drag<SVGGElement, RenderNode>().on('start', (event) => event.sourceEvent?.stopPropagation()).on('drag', (event, node) => this.callbacks.moveNode(node.id, { x: event.x, y: event.y })) as any);

        const endpointHalos = hoveredEdge ? [hoveredEdge.source, hoveredEdge.target].map((id) => ({ id, position: positions[id] ?? { x: 0, y: 0 } })) : [];
        this.labels.selectAll<SVGCircleElement, { id: string; position: Position }>('circle.edge-endpoint-halo').data(endpointHalos, (value) => value.id).join('circle').attr('class', 'edge-endpoint-halo').attr('r', 25).attr('cx', (value) => value.position.x).attr('cy', (value) => value.position.y).attr('fill', 'none').attr('stroke', 'var(--dox-brand-rubedo)').attr('stroke-width', 2).attr('pointer-events', 'none');
        this.labels.selectAll<SVGTextElement, RenderEdge>('text.edge-label').data(state.showLabels ? model.edges : [], (edge) => edge.id).join('text').attr('class', 'edge-label').attr('x', (edge) => ((positions[edge.source]?.x ?? 0) + (positions[edge.target]?.x ?? 0)) / 2).attr('y', (edge) => ((positions[edge.source]?.y ?? 0) + (positions[edge.target]?.y ?? 0)) / 2 - 8).text((edge) => edge.label);
        const anchorLabels = this.labels.selectAll<SVGGElement, LabelPlacement>('g.anchor-label').data(anchorPlacements, ({ node }) => node.id).join(
            (enter) => { const group = enter.append('g').attr('class', 'anchor-label').attr('aria-hidden', 'true'); group.append('rect'); group.append('text'); return group; },
            (update) => update,
            (exit) => exit.remove()
        );
        anchorLabels.attr('transform', ({ x, y }) => `translate(${(x - this.transform.x) * labelScale},${(y - this.transform.y) * labelScale}) scale(${labelScale})`);
        anchorLabels.select('rect').attr('width', ({ width }) => width).attr('height', 22).attr('rx', 2).attr('fill', 'var(--dox-ground)').attr('fill-opacity', .78).attr('stroke', 'var(--dox-rule-strong)').attr('stroke-opacity', .7);
        anchorLabels.select('text').attr('x', 7).attr('y', 15).text(({ node }) => node.label.length > 32 ? `${node.label.slice(0, 31)}…` : node.label);
        const interactedLabels = fullLabelId ? model.nodes.filter((node) => node.id === fullLabelId) : [];
        const labelCard = this.labels.selectAll<SVGGElement, RenderNode>('g.node-label-card').data(interactedLabels, (node) => node.id).join(
            (enter) => { const group = enter.append('g').attr('class', 'node-label-card').attr('aria-hidden', 'true'); group.append('rect'); group.append('text'); return group; },
            (update) => update,
            (exit) => exit.remove()
        );
        labelCard.attr('transform', (node) => `translate(${(positions[node.id]?.x ?? 0) + 28 * labelScale},${(positions[node.id]?.y ?? 0) - 32 * labelScale}) scale(${labelScale})`);
        labelCard.select('rect').attr('width', (node) => Math.min(360, Math.max(120, node.label.length * 7 + 16))).attr('height', 26).attr('rx', 3).attr('fill', 'var(--dox-ground)').attr('stroke', 'var(--dox-border)');
        labelCard.select('text').attr('x', 8).attr('y', 17).text((node) => node.label);
    }

    focus(id: string) {
        const position = this.positions[id];
        if (!position) return;
        const svg = this.svg.node();
        const width = svg?.clientWidth ?? 0;
        const height = svg?.clientHeight ?? 0;
        this.svg.transition().duration(this.motionDuration(250)).call(this.zoomBehavior.transform as any, zoomIdentity.translate(width / 2 - position.x, height / 2 - position.y).scale(this.transform.k) as any);
        this.nodes.selectAll<SVGGElement, RenderNode>('g.graph-node').filter((node) => node.id === id).node()?.focus();
    }

    fit(padding: number) {
        const values = Object.values(this.positions);
        if (!values.length) return;
        const svg = this.svg.node();
        const width = svg?.clientWidth ?? 0;
        const height = svg?.clientHeight ?? 0;
        const minX = Math.min(...values.map((point) => point.x)); const maxX = Math.max(...values.map((point) => point.x));
        const minY = Math.min(...values.map((point) => point.y)); const maxY = Math.max(...values.map((point) => point.y));
        const scale = Math.max(0.18, Math.min(3, Math.min((width - padding * 2) / Math.max(1, maxX - minX + 56), (height - padding * 2) / Math.max(1, maxY - minY + 56))));
        const transform = zoomIdentity.translate(width / 2 - ((minX + maxX) / 2) * scale, height / 2 - ((minY + maxY) / 2) * scale).scale(scale);
        this.svg.call(this.zoomBehavior.transform as any, transform as any);
    }

    clamp(padding: number) {
        const values = Object.values(this.positions);
        const svg = this.svg.node();
        if (!values.length || !svg) return;
        const width = svg.clientWidth;
        const height = svg.clientHeight;
        const scale = this.transform.k;
        const minX = Math.min(...values.map((point) => point.x)) - 28;
        const maxX = Math.max(...values.map((point) => point.x)) + 28;
        const minY = Math.min(...values.map((point) => point.y)) - 28;
        const maxY = Math.max(...values.map((point) => point.y)) + 28;
        const clampAxis = (translation: number, viewportSize: number, contentMin: number, contentMax: number) => {
            const scaledSize = (contentMax - contentMin) * scale;
            if (scaledSize <= viewportSize - padding * 2) return viewportSize / 2 - ((contentMin + contentMax) / 2) * scale;
            return Math.max(viewportSize - padding - contentMax * scale, Math.min(padding - contentMin * scale, translation));
        };
        const transform = zoomIdentity
            .translate(clampAxis(this.transform.x, width, minX, maxX), clampAxis(this.transform.y, height, minY, maxY))
            .scale(scale);
        this.svg.call(this.zoomBehavior.transform as any, transform as any);
    }

    private isOverview() { return !!this.model && this.model.nodes.length >= 80 && this.transform.k < 0.72; }

    private refreshScreenLabels() {
        const scale = 1 / Math.max(0.18, this.transform.k);
        const svg = this.svg.node();
        const width = svg?.clientWidth ?? 0;
        const height = svg?.clientHeight ?? 0;
        this.labels.selectAll<SVGGElement, { node: RenderNode; width: number }>('g.anchor-label')
            .attr('transform', ({ node, width: labelWidth }) => {
                const position = this.positions[node.id] ?? { x: 0, y: 0 };
                const screenX = position.x * this.transform.k + this.transform.x;
                const screenY = position.y * this.transform.k + this.transform.y;
                const x = screenX + 18 + labelWidth <= width - 8 ? screenX + 18 : screenX - labelWidth - 18;
                const y = Math.max(8, Math.min(height - 30, screenY - 14));
                return `translate(${(x - this.transform.x) * scale},${(y - this.transform.y) * scale}) scale(${scale})`;
            });
        this.labels.selectAll<SVGGElement, RenderNode>('g.node-label-card')
            .attr('transform', (node) => `translate(${(this.positions[node.id]?.x ?? 0) + 28 * scale},${(this.positions[node.id]?.y ?? 0) - 32 * scale}) scale(${scale})`);
    }

    private motionDuration(duration: number) { return globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 0 : duration; }
    zoomBy(factor: number) { this.svg.transition().duration(this.motionDuration(150)).call(this.zoomBehavior.scaleBy as any, factor); }
    destroy() { this.svg.on('.zoom', null); this.svg.selectAll('*').remove(); }
}
