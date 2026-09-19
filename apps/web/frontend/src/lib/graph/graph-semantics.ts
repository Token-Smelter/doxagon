import type { RenderEdge, RenderNode } from './graph-model';
import { seededNumber } from './graph-layout';

export interface EdgeSemantics {
    stroke: string;
    width: number;
    dash: string | null;
    marker: 'ink' | 'rubedo' | 'gold';
}

export function edgeSemantics(edge: RenderEdge): EdgeSemantics {
    if (edge.stoneEdge) return { stroke: 'var(--dox-brand-gold)', width: 2.5, dash: null, marker: 'gold' };
    if (/(contradict|tension)/i.test(edge.type)) return { stroke: 'var(--dox-brand-rubedo)', width: 2.25, dash: '7 5', marker: 'rubedo' };
    return { stroke: 'var(--dox-text-primary)', width: edge.type === 'depends' ? 2.5 : 1.5, dash: null, marker: 'ink' };
}

export function blotPath(node: RenderNode): string {
    if (node.kind === 'stone') return stonePath();
    const steps = 10;
    const points = Array.from({ length: steps }, (_, index) => {
        const angle = (Math.PI * 2 * index) / steps - Math.PI / 2;
        const wobble = 0.78 + seededNumber(`${node.slug}:${index}`) * 0.32;
        const radius = 19 * node.scale * wobble;
        return `${Math.cos(angle) * radius},${Math.sin(angle) * radius}`;
    });
    return `M ${points.join(' L ')} Z`;
}

export function stonePath(): string {
    return 'M 0,-22 A 22,22 0 1,1 0,22 A 22,22 0 1,1 0,-22 M -15,-15 H 15 V 15 H -15 Z M 0,-12 L 11,8 H -11 Z M 0,-6 A 6,6 0 1,1 0,6 A 6,6 0 1,1 0,-6';
}

export function defeaterPath(): string {
    return 'M -20,-6 A 21,21 0 0,1 -6,-20 M 6,-20 A 21,21 0 0,1 20,-6 M 20,6 A 21,21 0 0,1 6,20 M -6,20 A 21,21 0 0,1 -20,6 M -17,-13 L -26,-22 M 17,-13 L 26,-22 M 17,13 L 26,22 M -17,13 L -26,22';
}

export function satellitePositions(node: RenderNode): Array<{ x: number; y: number }> {
    return Array.from({ length: Math.min(5, node.evidenceCount) }, (_, index) => {
        const angle = (Math.PI * 2 * index) / Math.max(1, Math.min(5, node.evidenceCount)) - Math.PI / 2;
        return { x: Math.cos(angle) * (28 * node.scale), y: Math.sin(angle) * (28 * node.scale) };
    });
}

export function accessibleNodeLabel(node: RenderNode): string {
    const evidence = node.evidenceCount === 1 ? '1 evidence reference' : `${node.evidenceCount} evidence references`;
    return `${node.label}; ${evidence}${node.defeater ? '; defeater' : ''}${node.kind === 'stone' ? '; fixed output' : ''}`;
}

export function edgePath(source: { x: number; y: number }, target: { x: number; y: number }, curve: 'bezier' | 'unbundled-bezier' | 'taxi' | 'straight'): string {
    if (curve === 'straight') return `M ${source.x} ${source.y} L ${target.x} ${target.y}`;
    if (curve === 'taxi') return `M ${source.x} ${source.y} L ${(source.x + target.x) / 2} ${source.y} L ${(source.x + target.x) / 2} ${target.y} L ${target.x} ${target.y}`;
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const offset = curve === 'unbundled-bezier' ? 0.22 : 0.12;
    const cx = (source.x + target.x) / 2 - dy * offset;
    const cy = (source.y + target.y) / 2 + dx * offset;
    return `M ${source.x} ${source.y} Q ${cx} ${cy} ${target.x} ${target.y}`;
}
