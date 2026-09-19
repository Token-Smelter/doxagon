export interface DocumentCue {
    id: string;
    title: string;
    /** Doxa ids this cue rests on. Absent for every document that tells none. */
    claims?: string[];
}

export interface DocumentIdentity {
    documentId: string;
    edition: string;
}

export interface DocumentReady extends DocumentIdentity {
    type: 'ready';
    cues: DocumentCue[];
}

export interface DocumentPosition extends DocumentIdentity {
    type: 'position';
    cue: string;
    index: number;
    total: number;
    progress: number;
    chapter?: string;
}

export interface DocumentBridgeCallbacks {
    ready: (state: DocumentReady) => void;
    position: (state: DocumentPosition) => void;
    rejected: (reason: string) => void;
}

const MAX_CUES = 1_000;
const MAX_TEXT = 1_000;
/**
 * Each accepted claim costs the trusted host one vault fetch and one rendered
 * chip, so an untrusted document cannot declare an unbounded row of them.
 */
const MAX_CLAIMS_PER_CUE = 32;
const CLAIM_ID = /^d-[a-z0-9-]+$/;

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function boundedText(value: unknown): value is string {
    return typeof value === 'string' && value.length > 0 && value.length <= MAX_TEXT;
}

function parseClaims(value: unknown): string[] | null {
    if (!Array.isArray(value) || value.length > MAX_CLAIMS_PER_CUE) return null;
    const seen = new Set<string>();
    for (const claim of value) {
        if (!boundedText(claim) || !CLAIM_ID.test(claim) || seen.has(claim)) return null;
        seen.add(claim);
    }
    return [...value];
}

/**
 * The ready handshake, or null for every shape the host refuses.
 *
 * Claims are optional and additive: a cue that carries none is the cue every
 * document sent before tellings existed, and it parses unchanged. A cue that
 * declares more than MAX_CLAIMS_PER_CUE of them refuses the whole message
 * before anything is copied, fetched or rendered.
 */
export function parseDocumentReady(value: unknown): DocumentReady | null {
    if (!isRecord(value) || value.type !== 'ready' || !boundedText(value.documentId) || !boundedText(value.edition)) return null;
    if (!Array.isArray(value.cues) || value.cues.length === 0 || value.cues.length > MAX_CUES) return null;

    const seen = new Set<string>();
    const cues: DocumentCue[] = [];
    for (const candidate of value.cues) {
        if (!isRecord(candidate) || !boundedText(candidate.id) || !boundedText(candidate.title) || seen.has(candidate.id)) return null;
        seen.add(candidate.id);
        if (candidate.claims === undefined) {
            cues.push({ id: candidate.id, title: candidate.title });
            continue;
        }
        const claims = parseClaims(candidate.claims);
        if (claims === null) return null;
        cues.push({ id: candidate.id, title: candidate.title, claims });
    }
    return { type: 'ready', documentId: value.documentId, edition: value.edition, cues };
}

function parsePosition(value: unknown, ready: DocumentReady): DocumentPosition | null {
    if (!isRecord(value) || value.type !== 'position') return null;
    if (value.documentId !== ready.documentId || value.edition !== ready.edition) return null;
    if (typeof value.cue !== 'string' || typeof value.index !== 'number' || !Number.isInteger(value.index) || value.index < 0 || value.index >= ready.cues.length) return null;
    if (ready.cues[value.index]?.id !== value.cue || value.total !== ready.cues.length) return null;
    if (typeof value.progress !== 'number' || !Number.isFinite(value.progress) || value.progress < 0 || value.progress > 1) return null;
    if (value.chapter !== undefined && !boundedText(value.chapter)) return null;
    return {
        type: 'position',
        documentId: ready.documentId,
        edition: ready.edition,
        cue: value.cue,
        index: value.index,
        total: value.total,
        progress: value.progress,
        ...(typeof value.chapter === 'string' ? { chapter: value.chapter } : {}),
    };
}

/**
 * An opaque-origin document can only influence its host through this port. The
 * ready identity establishes the session; every later position must repeat it
 * and match the exact cue order before the host renders it.
 */
export class DocumentBridge {
    private port: MessagePort | null = null;
    private readyState: DocumentReady | null = null;
    private generation = 0;

    connect(target: Window, callbacks: DocumentBridgeCallbacks, expected: DocumentReady | null = null): void {
        this.dispose();
        const generation = ++this.generation;
        const channel = new MessageChannel();
        this.port = channel.port1;
        this.port.onmessage = (event: MessageEvent<unknown>) => {
            if (generation !== this.generation || this.port !== channel.port1) return;
            const message = event.data;
            if (this.readyState === null) {
                const ready = parseDocumentReady(message);
                if (ready === null || (expected !== null && JSON.stringify(ready) !== JSON.stringify(expected))) {
                    this.dispose();
                    callbacks.rejected('The document sent an invalid or mismatched bridge handshake.');
                } else {
                    this.readyState = ready;
                    callbacks.ready(ready);
                }
                return;
            }
            const position = parsePosition(message, this.readyState);
            if (position === null) {
                this.dispose();
                callbacks.rejected('The document sent an invalid position or a different document, edition or cue list.');
            } else callbacks.position(position);
        };
        this.port.onmessageerror = () => {
            if (generation !== this.generation) return;
            this.dispose();
            callbacks.rejected('The document sent an unreadable bridge message.');
        };
        this.port.start();
        target.postMessage({ type: 'doxagon:connect' }, '*', [channel.port2]);
    }

    get ready(): DocumentReady | null {
        return this.readyState;
    }

    send(command: 'next' | 'previous' | 'state'): boolean {
        if (this.port === null || this.readyState === null) return false;
        this.port.postMessage({ type: command });
        return true;
    }

    go(cue: string, instant = false): boolean {
        if (this.port === null || this.readyState === null || !this.readyState.cues.some((item) => item.id === cue)) return false;
        this.port.postMessage({ type: 'go', cue, ...(instant ? { instant: true } : {}) });
        return true;
    }

    dispose(): void {
        this.generation += 1;
        if (this.port) {
            this.port.onmessage = null;
            this.port.onmessageerror = null;
            this.port.close();
        }
        this.port = null;
        this.readyState = null;
    }
}

export function parseCompanionNotes(value: unknown, ready: DocumentReady): Map<string, string> | null {
    if (!isRecord(value) || value.documentId !== ready.documentId || value.edition !== ready.edition || !Array.isArray(value.cues)) return null;
    if (value.cues.length !== ready.cues.length) return null;
    const notes = new Map<string, string>();
    for (const [index, candidate] of value.cues.entries()) {
        if (!isRecord(candidate) || candidate.id !== ready.cues[index]?.id || typeof candidate.notes !== 'string') return null;
        notes.set(candidate.id, candidate.notes);
    }
    return notes;
}
