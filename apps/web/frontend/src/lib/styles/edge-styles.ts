// Renderer-neutral graph edge semantics. No adaptive/domain color assignment.
export interface EdgeStyle {
    color: string;
    width: number;
    style: 'solid' | 'dashed';
    arrow: 'triangle';
}

const INK: EdgeStyle = { color: 'var(--dox-text-primary)', width: 1.5, style: 'solid', arrow: 'triangle' };
const RUBEDO: EdgeStyle = { color: 'var(--dox-brand-rubedo)', width: 2.25, style: 'dashed', arrow: 'triangle' };

export function getEdgeStyle(type: string): EdgeStyle {
    return /(contradict|tension)/i.test(type) ? RUBEDO : INK;
}

export const EDGE_STYLES = { contradicts: RUBEDO, tension: RUBEDO, _default: INK };
export function getKnownEdgeTypes(): string[] { return ['contradicts', 'tension']; }
