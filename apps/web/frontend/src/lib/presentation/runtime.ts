/**
 * Loader for the one checkpoint runtime.
 *
 * `static/presentation-runtime.js` is a symlink to
 * `src/doxagon/presentations/resources/runtime.js`, the same bytes the offline
 * export inlines and the raster exporter drives. The workspace therefore
 * previews what it ships instead of approximating it.
 */

import type { DeckPayload, Snapshot } from './deck';

export const RUNTIME_URL = '/presentation-runtime.js';

export interface DeckState {
    schema: string;
    deckRevision: string;
    sequence: number;
    checkpointId: string | null;
    signature: string | null;
    diagnostics: string[];
}

export type DeckAction =
    | { type: 'SEEK'; checkpointId: string }
    | { type: 'NEXT' }
    | { type: 'PREVIOUS' }
    | { type: 'HOME' }
    | { type: 'END' };

export interface DeckRuntime {
    state(): DeckState;
    signatures(): Record<string, string>;
    seek(checkpointId: string): Promise<DeckState>;
    adopt(snapshot: Snapshot): Promise<DeckState>;
    cancel(): void;
    /** Latest-value continuous progress for an authored track; never navigation. */
    sample(track: string, progress: number): Promise<{ sampled: boolean }>;
    viewport(): Promise<{ innerWidth: number; innerHeight: number; scrollY: number; scrollHeight: number } | null>;
    dispatch(action: DeckAction): Promise<DeckState>;
    inspect(): Promise<Record<string, unknown> | null>;
    scroll(): Promise<{ scrollTop: number; scrollHeight: number; clientHeight: number } | null>;
    destroy(): Promise<unknown>;
}

interface RuntimeModule {
    RUNTIME_VERSION: string;
    createDeckRuntime(options: {
        deck: DeckPayload;
        mount: HTMLElement;
        reducedMotion?: boolean;
        onState?: (state: DeckState) => void;
    }): DeckRuntime;
    attachControls(runtime: DeckRuntime, target?: EventTarget): () => void;
}

let loaded: Promise<RuntimeModule> | null = null;

export function loadRuntime(): Promise<RuntimeModule> {
    if (loaded === null) loaded = import(/* @vite-ignore */ RUNTIME_URL) as Promise<RuntimeModule>;
    return loaded;
}
