import { writable, derived } from 'svelte/store';
import type { PipelineStats, PhantasiaListItem, EvidenceListItem, PhantasiaStatus, EvidenceStatus } from '../api';

export const pipelineStats = writable<PipelineStats | null>(null);
export const phantasiai = writable<PhantasiaListItem[]>([]);
export const evidence = writable<EvidenceListItem[]>([]);

export const selectedPhantasia = writable<string | null>(null);
export const selectedEvidence = writable<string | null>(null);

export const phantasiaStatusFilter = writable<PhantasiaStatus | null>(null);
export const evidenceStatusFilter = writable<EvidenceStatus | null>(null);

export const filteredPhantasiai = derived(
    [phantasiai, phantasiaStatusFilter],
    ([$phantasiai, $filter]) => {
        if (!$filter) return $phantasiai;
        return $phantasiai.filter(p => p.status === $filter);
    }
);

export const filteredEvidence = derived(
    [evidence, evidenceStatusFilter],
    ([$evidence, $filter]) => {
        if (!$filter) return $evidence;
        return $evidence.filter(e => e.status === $filter);
    }
);

export const totalPhantasiai = derived(
    pipelineStats,
    ($stats) => {
        if (!$stats) return 0;
        return Object.values($stats.phantasiai).reduce((a, b) => a + b, 0);
    }
);
