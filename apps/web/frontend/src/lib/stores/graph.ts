import { writable, derived } from 'svelte/store';
import type { Graph } from '../api';

export const graph = writable<Graph | null>(null);
export const selectedNode = writable<string | null>(null);
export const selectedEdge = writable<{ source: string; target: string } | null>(null);
export const activeDiegesis = writable<string | null>(null);
export const activeWalk = writable<string | null>(null);  // Selected walk within a diegesis
export const neighborhoodRoot = writable<string | null>(null);
export const neighborhoodHops = writable<number>(2);
export const searchQuery = writable<string>('');

// Action store for focus requests - triggers graph animation to node
export const focusRequest = writable<string | null>(null);

// Impact analysis - triggers downstream highlight
export const impactRequest = writable<string | null>(null);
export const impactCount = writable<number>(0);

// Layout selection
export type LayoutType = 'fcose' | 'breadthfirst' | 'concentric' | 'circle';
export const selectedLayout = writable<LayoutType>('fcose');

// Graph display settings
export type CurveStyle = 'bezier' | 'unbundled-bezier' | 'taxi' | 'straight';
export const showEdgeLabels = writable<boolean>(false);
export const nodeSpacing = writable<number>(100); // 50-200 range
export const curveStyle = writable<CurveStyle>('unbundled-bezier');

export const filteredNodes = derived(
    [graph, searchQuery],
    ([$graph, $searchQuery]) => {
        if (!$graph) return [];
        if (!$searchQuery) return $graph.nodes;
        const q = $searchQuery.toLowerCase();
        return $graph.nodes.filter(n =>
            n.title.toLowerCase().includes(q) ||
            n.tags.some(t => t.toLowerCase().includes(q))
        );
    }
);
