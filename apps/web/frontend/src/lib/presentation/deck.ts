/**
 * Client for one selected presentation's revisioned checkpoint workspace.
 *
 * Every read answers with the revision as a strong ETag and every mutation
 * sends that exact tag back as If-Match, so a stale editor is refused rather
 * than silently overwriting someone else's revision. There is no selected
 * image, primary flag, or layout mode in this surface: a checkpoint's position
 * is its index in `checkpoint_order`, and an asset is referenced explicitly or
 * not at all.
 *
 * The base path names the presentation being edited. There is no module-level
 * default: a client that could not say which presentation it addressed would
 * be a second, detached authority beside the one the user selected.
 */

/** Where the hosted app mounts one vault presentation's Step workspace. */
export const presentationBase = (presentationSlug: string): string =>
    `/api/presentations/${encodeURIComponent(presentationSlug)}`;

export interface CheckpointSource {
    role: string;
    path: string;
    sha256: string;
    bytes: number;
}

export interface CheckpointView {
    id: string;
    index: number;
    label: string;
    groups: string[];
    assets: string[];
    capabilities: string[];
    sources: CheckpointSource[];
    status: string;
}

export interface GroupView {
    id: string;
    kind: string;
    label: string;
    checkpoints: string[];
    export_boundary?: boolean;
}

export interface AssetProvenance {
    kind: string;
    created_at: string;
    generator: string | null;
    prompt_sha256: string | null;
    source_ref: string | null;
    license: string | null;
}

export interface AssetGeneration {
    job_id: string;
    status: string;
    prompt_sha256: string | null;
    /** The exact text the generator was given; `prompt_sha256` attests to it. */
    prompt: string | null;
    prompt_references: string[];
    variant_index: number | null;
    requested_for: string | null;
}

/** One reusable prompt fragment the deck stores, and its reference assets. */
export interface StyleView {
    id: string;
    text: string;
    references: string[];
}

export interface AssetView {
    id: string;
    label: string;
    alt: string | null;
    media_type: string;
    bytes: number;
    sha256: string;
    storage_key: string;
    provenance: AssetProvenance;
    referenced_by: string[];
    generation: AssetGeneration | null;
    thumbnail: boolean;
}

export interface WorkspaceView {
    revision: string;
    checkpoint_order: string[];
    checkpoints: CheckpointView[];
    groups: GroupView[];
    assets: AssetView[];
    styles: StyleView[];
}

/**
 * One durable job record, exactly as `JobRecord.as_dict` emits it.
 *
 * A job is listed whatever it produced, including a failed one that produced
 * nothing: a surface that could only reach a job through the assets it admitted
 * would never show the one job a retry exists for.
 */
export interface JobView {
    schema: string;
    job_id: string;
    kind: string;
    status: string;
    idempotency_key: string;
    base_revision: string;
    request: Record<string, unknown>;
    outputs: Record<string, unknown>[];
    /** Per-variant refusals, in the producer's own vocabulary. */
    failures: { code: string; message: string; [key: string]: unknown }[];
    error: { code: string; message: string } | null;
    revision: string | null;
    retry_of: string | null;
    attempt: number;
    created_at: string;
    updated_at: string;
    lineage: string;
}

/**
 * The one status `JobStore.retry` accepts.
 *
 * `src/doxagon/presentations/jobs.py` refuses a retry of any other status with
 * PRES_JOB_NOT_RETRYABLE, so offering the control anywhere else would render a
 * button whose only possible answer is a refusal.
 */
export const RETRYABLE_JOB_STATUS = 'failed';

/** One checkpoint's generation request, as `specs_from_request` reads it. */
export interface GenerationTarget {
    checkpoint_id: string;
    label: string;
    alt: string;
    description: string;
    aspect_ratio?: string;
    resolution?: string;
    variants?: number;
    references?: string[];
    /** Ids of the deck's stored styles this target composes into its prompt. */
    styles?: string[];
}

/**
 * A proposal the server's configured author wrote for one scoped task.
 *
 * The bytes in `proposal` are the author's, not the editor's: the editor sends
 * an instruction and shows what comes back, and the human approving it promotes
 * exactly these bytes through the ordinary patch path.
 */
export interface AgentProposal {
    schema: string;
    task_id: string;
    checkpoint_id: string;
    base_revision: string;
    role: string;
    instruction: string;
    author: string;
    proposal: string;
    proposal_sha256: string;
}

/**
 * One built raster archive, as `POST /exports/raster` answered with it.
 *
 * The bytes are the server's: `export_raster` drives the configured browser
 * runtime over the closed offline document and seals the frames, their
 * signatures, and `export-manifest.json` into the ZIP. The client only names
 * the revision and digest the response reported, so a caller cannot present a
 * build no capturer produced.
 */
export interface RasterExport {
    archive: Blob;
    revision: string | null;
    digest: string | null;
}

export interface DeckEdge {
    id: string;
    from: string;
    to: string;
    forward: Record<string, unknown>;
    reverse: Record<string, unknown>;
    duration_ms: number | null;
    timeout_ms?: number;
    export_boundary: boolean;
    generated: boolean;
}

export interface DeckCheckpoint {
    id: string;
    scene?: string;
    mode?: 'stage' | 'document';
    cues?: string[];
    /** What the presenter says at each cue; private, never in a public export. */
    cue_notes?: Record<string, string>;
    label: string;
    groups: string[];
    capabilities: string[];
    modules: string[];
    registration: Record<string, unknown> | null;
    entry: string;
    document: string;
    styles: string;
    notes: string | null;
    assets: { id: string; label: string; alt: string | null; media_type: string; base64: string }[];
}

export interface DeckPayload {
    schema: string;
    presentation_id: string;
    revision: string;
    runtime_version: string;
    runtime_sha256: string;
    compose_hash: string;
    capability_grants: Record<string, string[]>;
    export_policy: Record<string, unknown>;
    checkpoint_order: string[];
    checkpoints: DeckCheckpoint[];
    edges: DeckEdge[];
    groups: GroupView[];
}

/**
 * The only cursor record a client is allowed to believe.
 *
 * The server issues every snapshot; nothing here mints one. A client may relay
 * a snapshot it received, but a position it invented has no standing.
 */
export interface Snapshot {
    schema: string;
    session_id: string;
    deck_revision: string;
    epoch: number;
    sequence: number;
    checkpoint_id: string;
    /** Where inside a document-mode checkpoint the cursor rests, if anywhere. */
    cue?: string | null;
    issued_at: string;
    navigation?: { type: DeckActionRequest['type']; from: string; from_cue?: string } | null;
}

export interface DeckActionRequest {
    type: 'SEEK' | 'NEXT' | 'PREVIOUS' | 'HOME' | 'END';
    checkpointId?: string | null;
    /** Seek a position inside a document-mode checkpoint. */
    cue?: string | null;
}

/** The patch schema `AgentPatch.parse` requires, verbatim. */
export const AGENT_PATCH_SCHEMA = 'doxagon.presentation-agent-patch/2';

/** Exactly the context fields a patch is refused for omitting. */
export const AGENT_CONTEXT_FIELDS = ['task_id', 'base_revision', 'checkpoint_id', 'before_digest'] as const;

export interface AgentEditableSource {
    role: string;
    path: string;
}

export interface AgentScope {
    checkpoint_id: string;
    allowed_operations: string[];
    denied_operations: string[];
    editable_sources: AgentEditableSource[];
    capability_vocabulary: string[];
}

export interface AgentTaskSource {
    role: string;
    path: string;
    sha256: string;
    text: string | null;
}

export interface AgentTaskCheckpoint {
    id: string;
    label: string;
    index: number;
    source: string;
    groups: string[];
    sources: AgentTaskSource[];
    registration: Record<string, unknown> | null;
    assets: string[];
    capabilities: string[];
}

export interface AgentCheckpointState {
    revision: string;
    checkpoint_id: string;
    index: number;
    label: string;
    sources: CheckpointSource[];
    capabilities: string[];
    preview: { preview_sha256: string; [key: string]: unknown };
    signature: { status: string; runtime: string; value: string | null };
    [key: string]: unknown;
}

/**
 * The task the server issues, exactly as `build_task` assembles it
 * (`src/doxagon/presentations/agent.py`).
 *
 * The checkpoint this task is scoped to is `scope.checkpoint_id`, the state it
 * was written against is pinned by `before_digest`, and there is no top-level
 * `checkpoint_id` or `base_state_digest` member: a client that reads either of
 * those names reads `undefined` and submits a patch the server must refuse.
 */
export interface AgentTask {
    schema: string;
    task_id: string;
    created_at: string;
    presentation_id: string;
    base_revision: string;
    /** True once the deck moved past `base_revision`; such a patch cannot land. */
    stale: boolean;
    scope: AgentScope;
    checkpoint: AgentTaskCheckpoint;
    edges: { incoming: Record<string, unknown>[]; outgoing: Record<string, unknown>[] };
    neighbours: { predecessor: Record<string, unknown> | null; successor: Record<string, unknown> | null };
    before: AgentCheckpointState;
    before_digest: string;
    validation: Record<string, unknown>;
    [key: string]: unknown;
}

/**
 * The patch body `AgentPatch.parse` accepts.
 *
 * `sources` is a role-keyed mapping of whole file text, not an array of
 * records: a role names the only bytes this task can reach, so a path never
 * travels in a patch.
 */
export interface AgentPatch {
    schema: typeof AGENT_PATCH_SCHEMA;
    task_id: string;
    base_revision: string;
    checkpoint_id: string;
    before_digest: string;
    sources?: Record<string, string>;
    label?: string;
    assets?: string[];
    capabilities?: string[];
    summary?: string;
}

export interface AgentSourceDiff {
    path: string;
    role: string;
    before_sha256: string | null;
    after_sha256: string | null;
    changed: boolean;
}

export interface AgentOutcome {
    schema: string;
    task_id: string;
    checkpoint_id: string;
    base_revision: string;
    revision: string;
    summary: string | null;
    before: AgentCheckpointState;
    after: AgentCheckpointState;
    diff: {
        sources: AgentSourceDiff[];
        preview: { before: string; after: string; changed: boolean };
        [key: string]: unknown;
    };
    assets_admitted: string[];
    receipt: Record<string, unknown>;
    [key: string]: unknown;
}

/** A refusal the client makes on its own, before any patch is submitted. */
export class AgentContextError extends Error {
    code: string;

    constructor(code: string, message: string) {
        super(message);
        this.name = 'AgentContextError';
        this.code = code;
    }
}

/**
 * Build the patch for one scoped edit, or refuse to build one at all.
 *
 * The context travels from the issued task and nowhere else, so a task that is
 * missing a required field, that names a role this task cannot write, or that
 * the server already reported stale never becomes a submitted patch. The
 * server enforces all three again; this only keeps the editor from asking for
 * something it has been told cannot land.
 */
export function agentPatchFor(
    task: AgentTask,
    edit: { sources?: Record<string, string>; label?: string; summary?: string },
): AgentPatch {
    const context = {
        task_id: task?.task_id,
        base_revision: task?.base_revision,
        checkpoint_id: task?.scope?.checkpoint_id,
        before_digest: task?.before_digest,
    };
    const missing = AGENT_CONTEXT_FIELDS.filter((field) => typeof context[field] !== 'string' || context[field] === '');
    if (missing.length > 0) {
        throw new AgentContextError(
            'PRES_AGENT_CONTEXT_INCOMPLETE',
            // The missing members are named in the contract's own vocabulary:
            // they are the fields the server refuses the patch for omitting,
            // and a product paraphrase would not be findable in a log.
            `this AI edit published no ${missing.join(', ')}; an edit without its context cannot be reviewed`,
        );
    }
    if (task.stale === true) {
        throw new AgentContextError(
            'PRES_AGENT_TASK_STALE',
            'this AI edit was issued against an older revision; re-open it before approving',
        );
    }
    const editable = new Set((task.scope.editable_sources ?? []).map((item) => item.role));
    for (const role of Object.keys(edit.sources ?? {})) {
        if (!editable.has(role)) {
            throw new AgentContextError(
                'PRES_AGENT_SCOPE_VIOLATION',
                `this AI edit cannot write the ${role} source of ${context.checkpoint_id}`,
            );
        }
    }
    return {
        schema: AGENT_PATCH_SCHEMA,
        ...(context as Record<(typeof AGENT_CONTEXT_FIELDS)[number], string>),
        ...(edit.sources === undefined ? {} : { sources: edit.sources }),
        ...(edit.label === undefined ? {} : { label: edit.label }),
        ...(edit.summary === undefined ? {} : { summary: edit.summary }),
    } as AgentPatch;
}

/**
 * One structured diagnostic, exactly as `Diagnostic.as_dict` emits it
 * (`src/doxagon/presentations/errors.py`).
 *
 * A refusal that carries these is only actionable with all of them: the server
 * reports every independent finding in one pass, so the client keeps the whole
 * array rather than its length.
 */
export interface MigrationDiagnostic {
    code: string;
    message: string;
    pointer: string;
    path: string | null;
    line: number | null;
}

/** Read one diagnostic record without discarding a member it does carry. */
function diagnosticFrom(raw: unknown): MigrationDiagnostic {
    const item = (raw ?? {}) as Record<string, unknown>;
    return {
        code: typeof item.code === 'string' ? item.code : '',
        message: typeof item.message === 'string' ? item.message : '',
        pointer: typeof item.pointer === 'string' ? item.pointer : '',
        path: typeof item.path === 'string' ? item.path : null,
        line: typeof item.line === 'number' ? item.line : null,
    };
}

export class DeckRequestError extends Error {
    code: string;
    status: number;
    revision: string | null;
    /**
     * Every diagnostic the refusal published, in the server's own order.
     *
     * `WorkspaceError.as_dict` always emits this member, so an empty array
     * means the refusal published none — never that the client dropped them.
     */
    diagnostics: MigrationDiagnostic[];

    constructor(
        code: string,
        message: string,
        status: number,
        revision: string | null,
        diagnostics: MigrationDiagnostic[] = [],
    ) {
        super(message);
        this.name = 'DeckRequestError';
        this.code = code;
        this.status = status;
        this.revision = revision;
        this.diagnostics = diagnostics;
    }
}

async function requestFrom(base: string, path: string, init: RequestInit = {}): Promise<Response> {
    const response = await fetch(`${base}${path}`, init);
    if (response.ok) return response;
    let code = `HTTP_${response.status}`;
    let message = response.statusText;
    let revision: string | null = null;
    let diagnostics: MigrationDiagnostic[] = [];
    try {
        const body = await response.json();
        code = typeof body.code === 'string' ? body.code : code;
        message = typeof body.message === 'string' ? body.message : message;
        revision = typeof body.revision === 'string' ? body.revision : null;
        // Every entry travels, one for one. Summarising them into a count here
        // is exactly what left an operator with a number and no next step.
        diagnostics = Array.isArray(body.diagnostics) ? body.diagnostics.map(diagnosticFrom) : [];
    } catch {
        // A non-JSON failure keeps its status; inventing a code would be worse.
    }
    throw new DeckRequestError(code, message, response.status, revision, diagnostics);
}

/** The refusal `plan_migration` raises when a legacy tree is ambiguous. */
export const MIGRATION_BLOCKED = 'PRES_MIGRATION_BLOCKED';

/** The refusal `plan_migration` raises when a legacy tree registers no slide. */
export const MIGRATION_EMPTY = 'PRES_MIGRATION_EMPTY';

/**
 * What each migration refusal means to the person who opened the presentation.
 *
 * The key is the producer's code, verbatim, so a copy line can be traced to the
 * diagnostic that raised it (`src/doxagon/presentations/migration.py`). The
 * value is product language: it names slides, images, and settings, never the
 * storage contract. A code with no line here still renders — with the generic
 * sentence below and its own code and server message as detail — because a
 * blocker nobody wrote copy for is still a blocker the operator must see.
 */
const MIGRATION_SUMMARIES: Record<string, string> = {
    PRES_MIGRATION_ORDER_UNDECLARED:
        'This presentation needs a slide order. Its folders do not form a complete numbered sequence.',
    PRES_MIGRATION_ORDER_UNREADABLE:
        'The presentation settings file could not be read, so its slide order is unknown.',
    PRES_MIGRATION_SLIDE_UNORDERED:
        'This slide exists in the project, but the declared order never names it.',
    PRES_MIGRATION_SLIDE_MISSING: 'The declared order names this slide, but its files are not there.',
    PRES_MIGRATION_SLIDE_DUPLICATE: 'The declared order names this slide more than once.',
    PRES_MIGRATION_SLIDE_UNREADABLE: 'This slide’s text could not be read.',
    PRES_MIGRATION_ID_COLLISION: 'Two slides would end up sharing one identifier.',
    PRES_MIGRATION_SELECTION_ABSENT:
        'This slide offers more than one image and records no choice between them.',
    PRES_MIGRATION_SELECTION_MISSING:
        'This slide names a chosen image that is not one of the images it holds.',
    PRES_MIGRATION_SELECTION_UNCONTAINED:
        'This slide names a chosen image by a path that points outside its own image folder.',
    PRES_MIGRATION_CANDIDATE_UNREADABLE: 'An image file this slide holds could not be read.',
    PRES_MIGRATION_BUNDLE_INVALID: 'One of this slide’s image entries is not written in a readable form.',
    PRES_MIGRATION_HTML_MISSING:
        'This slide is authored as hand-written HTML, but the HTML file is not there.',
    PRES_MIGRATION_HTML_UNREADABLE: 'This slide’s HTML file could not be read.',
    PRES_MIGRATION_HTML_UNSAFE: 'This slide’s HTML runs script that cannot be carried across safely.',
    PRES_MIGRATION_EMPTY: 'No slide has been authored for this presentation yet.',
};

const MIGRATION_FALLBACK = 'This part of the presentation needs a decision before it can be opened.';

/** One diagnostic, ready to render: product copy first, producer detail after. */
export interface MigrationBlocker {
    code: string;
    summary: string;
    /** The producer's own sentence, kept verbatim as secondary detail. */
    detail: string;
    /** Where the producer located it, `path` or `path:line`, or ''. */
    location: string;
}

/** Every blocker the producer located against one slide or one file. */
export interface MigrationBlockerGroup {
    subject: string;
    kind: 'slide' | 'file';
    blockers: MigrationBlocker[];
}

export type MigrationOutcome =
    | { kind: 'blocked'; total: number; groups: MigrationBlockerGroup[] }
    | { kind: 'empty' };

/**
 * The slide or file one diagnostic is about.
 *
 * The producer locates a slide-level finding by its slug and a file-level one
 * by a revision-relative path (`01-intro/slide.html`, `config.yaml`), so the
 * first path segment is the subject and a segment carrying an extension is a
 * file rather than a slide.
 */
function subjectOf(diagnostic: MigrationDiagnostic): { subject: string; kind: 'slide' | 'file' } {
    const located = (diagnostic.path ?? '').trim();
    if (located === '') return { subject: 'This presentation', kind: 'file' };
    const head = located.split('/')[0];
    return { subject: head, kind: head.includes('.') ? 'file' : 'slide' };
}

/**
 * Group every diagnostic by the slide or file it names, in the server's order.
 *
 * The server already sorts its findings deterministically
 * (`DiagnosticLog.sorted`, `inventory_presentation`), so first appearance is a
 * stable order and grouping preserves it. Nothing is filtered: the number of
 * rendered rows equals the number of diagnostics the refusal carried.
 */
export function migrationBlockers(diagnostics: MigrationDiagnostic[]): MigrationBlockerGroup[] {
    const groups: MigrationBlockerGroup[] = [];
    const index = new Map<string, MigrationBlockerGroup>();
    for (const diagnostic of diagnostics) {
        const { subject, kind } = subjectOf(diagnostic);
        let group = index.get(subject);
        if (group === undefined) {
            group = { subject, kind, blockers: [] };
            index.set(subject, group);
            groups.push(group);
        }
        const located = (diagnostic.path ?? '').trim();
        group.blockers.push({
            code: diagnostic.code,
            summary: MIGRATION_SUMMARIES[diagnostic.code] ?? MIGRATION_FALLBACK,
            detail: diagnostic.message,
            location: located === '' ? '' : diagnostic.line === null ? located : `${located}:${diagnostic.line}`,
        });
    }
    return groups;
}

/**
 * How an open failure should read, or nothing when it is an ordinary refusal.
 *
 * A tree that registers no slide has nothing wrong with it — it simply has no
 * presentation yet — so it reads as an empty state rather than a failure. A
 * blocked tree reads as the full list of what a person must decide. Anything
 * else, including a blocked refusal that published no diagnostic, falls back to
 * the caller's ordinary failure reporting rather than rendering an empty list.
 */
export function migrationOutcome(error: unknown): MigrationOutcome | null {
    if (!(error instanceof DeckRequestError)) return null;
    if (error.code === MIGRATION_EMPTY) return { kind: 'empty' };
    if (error.code !== MIGRATION_BLOCKED || error.diagnostics.length === 0) return null;
    if (error.diagnostics.every((item) => item.code === MIGRATION_EMPTY)) return { kind: 'empty' };
    return {
        kind: 'blocked',
        total: error.diagnostics.length,
        groups: migrationBlockers(error.diagnostics),
    };
}

const withMatch = (revision: string, extra: Record<string, string> = {}) => ({
    'If-Match': `"${revision}"`,
    ...extra,
});

/**
 * Whether a client holding `current` may adopt `candidate`.
 *
 * This mirrors the server's own acceptance rule so a relayed snapshot from a
 * foreign revision, a stale pair, or a forked pair is rejected locally instead
 * of moving the cursor backwards.
 */
export function acceptsSnapshot(current: Snapshot | null, candidate: Snapshot): boolean {
    if (current === null) return true;
    if (candidate.session_id !== current.session_id) return false;
    if (candidate.deck_revision !== current.deck_revision) return false;
    if (candidate.epoch !== current.epoch) return candidate.epoch > current.epoch;
    if (candidate.sequence === current.sequence) {
        return candidate.checkpoint_id === current.checkpoint_id && (candidate.cue ?? null) === (current.cue ?? null);
    }
    return candidate.sequence > current.sequence;
}

/**
 * Every call one selected presentation's editor, presenter, and audience make.
 *
 * The client is bound to a base path once, so no call site can address a
 * presentation other than the one the session was opened for.
 */
export interface PresentationClient {
    readonly base: string;
    readWorkspace(): Promise<WorkspaceView>;
    readDeck(): Promise<DeckPayload>;
    openSession(revision?: string, sessionId?: string): Promise<Snapshot>;
    readSession(sessionId: string): Promise<Snapshot>;
    applyAction(sessionId: string, action: DeckActionRequest, expectedRevision?: string): Promise<Snapshot>;
    repinSession(sessionId: string, revision: string): Promise<Snapshot>;
    addCheckpoint(revision: string, label: string, after?: string | null): Promise<WorkspaceView>;
    deleteCheckpoint(revision: string, checkpointId: string): Promise<WorkspaceView>;
    relabelCheckpoint(revision: string, checkpointId: string, label: string): Promise<WorkspaceView>;
    reorderCheckpoints(revision: string, checkpointOrder: string[]): Promise<WorkspaceView>;
    putSource(revision: string, checkpointId: string, role: string, body: string): Promise<WorkspaceView>;
    setCheckpointAssets(revision: string, checkpointId: string, assets: string[]): Promise<WorkspaceView>;
    setCheckpointCapabilities(revision: string, checkpointId: string, capabilities: string[]): Promise<WorkspaceView>;
    setCheckpointTransition(
        revision: string,
        checkpointId: string,
        transition: Record<string, unknown> | null,
    ): Promise<WorkspaceView>;
    putGroup(
        revision: string,
        groupId: string,
        group: { kind: string; label: string; checkpoints: string[]; export_boundary?: boolean },
    ): Promise<WorkspaceView>;
    deleteGroup(revision: string, groupId: string): Promise<WorkspaceView>;
    putStyle(revision: string, styleId: string, style: Omit<StyleView, 'id'>): Promise<WorkspaceView>;
    deleteStyle(revision: string, styleId: string): Promise<WorkspaceView>;
    deleteAsset(revision: string, assetId: string): Promise<WorkspaceView>;
    listJobs(): Promise<JobView[]>;
    startGeneration(idempotencyKey: string, targets: GenerationTarget[]): Promise<JobView>;
    runJob(jobId: string): Promise<JobView>;
    retryJob(jobId: string): Promise<JobView>;
    openAgentTask(checkpointId: string, grants?: string[]): Promise<AgentTask>;
    proposeAgentEdit(taskId: string, role: string, instruction: string): Promise<AgentProposal>;
    applyAgentPatch(revision: string, taskId: string, patch: AgentPatch): Promise<AgentOutcome>;
    exportRaster(groups?: string[] | null): Promise<RasterExport>;
    exportUrl(format: 'offline-html' | 'source-archive'): string;
    assetThumbnailUrl(assetId: string): string;
}

/** Bind every workspace call to exactly one presentation. */
export function presentationClient(base: string): PresentationClient {
    const request = (path: string, init: RequestInit = {}) => requestFrom(base, path, init);
    return {
        base,

        async readWorkspace() {
            return (await request('')).json();
        },

        async readDeck() {
            return (await request('/deck')).json();
        },

        /** Open (or restart) a server-owned session pinned to one revision. */
        async openSession(revision?: string, sessionId?: string) {
            return (await request('/sessions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ revision: revision ?? null, session_id: sessionId ?? null }),
            })).json();
        },

        async readSession(sessionId: string) {
            return (await request(`/sessions/${encodeURIComponent(sessionId)}`)).json();
        },

        /** Send one action; the answer is the new authoritative cursor. */
        async applyAction(sessionId: string, action: DeckActionRequest, expectedRevision?: string) {
            return (await request(`/sessions/${encodeURIComponent(sessionId)}/actions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    type: action.type,
                    checkpointId: action.checkpointId ?? null,
                    cue: action.cue ?? null,
                    expected_revision: expectedRevision ?? null,
                }),
            })).json();
        },

        /** Move a live session onto another revision by ending the current epoch. */
        async repinSession(sessionId: string, revision: string) {
            return (await request(`/sessions/${encodeURIComponent(sessionId)}/repin`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ revision }),
            })).json();
        },

        async addCheckpoint(revision: string, label: string, after: string | null = null) {
            return (await request('/checkpoints', {
                method: 'POST',
                headers: withMatch(revision, { 'Content-Type': 'application/json' }),
                body: JSON.stringify({ label, after }),
            })).json();
        },

        async deleteCheckpoint(revision: string, checkpointId: string) {
            return (await request(`/checkpoints/${encodeURIComponent(checkpointId)}`, {
                method: 'DELETE',
                headers: withMatch(revision),
            })).json();
        },

        async relabelCheckpoint(revision: string, checkpointId: string, label: string) {
            return (await request(`/checkpoints/${encodeURIComponent(checkpointId)}`, {
                method: 'PATCH',
                headers: withMatch(revision, { 'Content-Type': 'application/json' }),
                body: JSON.stringify({ label }),
            })).json();
        },

        async reorderCheckpoints(revision: string, checkpointOrder: string[]) {
            return (await request('/checkpoint-order', {
                method: 'PUT',
                headers: withMatch(revision, { 'Content-Type': 'application/json' }),
                body: JSON.stringify({ checkpoint_order: checkpointOrder }),
            })).json();
        },

        async putSource(revision: string, checkpointId: string, role: string, body: string) {
            return (await request(
                `/checkpoints/${encodeURIComponent(checkpointId)}/sources/${encodeURIComponent(role)}`,
                { method: 'PUT', headers: withMatch(revision, { 'Content-Type': 'text/plain' }), body },
            )).json();
        },

        async setCheckpointAssets(revision: string, checkpointId: string, assets: string[]) {
            return (await request(`/checkpoints/${encodeURIComponent(checkpointId)}/assets`, {
                method: 'PUT',
                headers: withMatch(revision, { 'Content-Type': 'application/json' }),
                body: JSON.stringify({ assets }),
            })).json();
        },

        async setCheckpointCapabilities(revision: string, checkpointId: string, capabilities: string[]) {
            return (await request(`/checkpoints/${encodeURIComponent(checkpointId)}/capabilities`, {
                method: 'PUT',
                headers: withMatch(revision, { 'Content-Type': 'application/json' }),
                body: JSON.stringify({ capabilities }),
            })).json();
        },

        /**
         * Rewrite one checkpoint's half of its registered edges.
         *
         * Passing `null` retires this checkpoint's halves. The server refuses a
         * one-directional or unregistered edge, so a half-edit is rejected
         * rather than landed.
         */
        async setCheckpointTransition(
            revision: string,
            checkpointId: string,
            transition: Record<string, unknown> | null,
        ) {
            return (await request(`/checkpoints/${encodeURIComponent(checkpointId)}/transition`, {
                method: 'PUT',
                headers: withMatch(revision, { 'Content-Type': 'application/json' }),
                body: JSON.stringify({ transition }),
            })).json();
        },

        async putGroup(
            revision: string,
            groupId: string,
            group: { kind: string; label: string; checkpoints: string[]; export_boundary?: boolean },
        ) {
            return (await request(`/groups/${encodeURIComponent(groupId)}`, {
                method: 'PUT',
                headers: withMatch(revision, { 'Content-Type': 'application/json' }),
                body: JSON.stringify(group),
            })).json();
        },

        async deleteGroup(revision: string, groupId: string) {
            return (await request(`/groups/${encodeURIComponent(groupId)}`, {
                method: 'DELETE',
                headers: withMatch(revision),
            })).json();
        },

        async putStyle(revision: string, styleId: string, style: Omit<StyleView, 'id'>) {
            return (await request(`/styles/${encodeURIComponent(styleId)}`, {
                method: 'PUT',
                headers: withMatch(revision, { 'Content-Type': 'application/json' }),
                body: JSON.stringify(style),
            })).json();
        },

        async deleteStyle(revision: string, styleId: string) {
            return (await request(`/styles/${encodeURIComponent(styleId)}`, {
                method: 'DELETE',
                headers: withMatch(revision),
            })).json();
        },

        async deleteAsset(revision: string, assetId: string) {
            return (await request(`/assets/${encodeURIComponent(assetId)}`, {
                method: 'DELETE',
                headers: withMatch(revision),
            })).json();
        },

        /** Every job this workspace holds, whatever it produced or failed to. */
        async listJobs() {
            return (await (await request('/jobs')).json()).jobs;
        },

        /**
         * Record one generation request; the key makes a resubmission a replay.
         *
         * Submitting only records the request. Producing bytes is `runJob`,
         * which is a separate act because a backend failure has to land on a
         * durable record rather than on whichever request happened to be open.
         */
        async startGeneration(idempotencyKey: string, targets: GenerationTarget[]) {
            return (await request('/generations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ idempotency_key: idempotencyKey, targets, defaults: {}, styles: [] }),
            })).json();
        },

        /** Execute a recorded job and answer with the record it finished as. */
        async runJob(jobId: string) {
            return (await request(`/jobs/${encodeURIComponent(jobId)}/run`, { method: 'POST' })).json();
        },

        /**
         * Re-submit failed work against the revision that is current now.
         *
         * The answer is a *new pending* record, so a caller that stopped here
         * would leave the retry it asked for unexecuted.
         */
        async retryJob(jobId: string) {
            return (await request(`/jobs/${encodeURIComponent(jobId)}/retry`, { method: 'POST' })).json();
        },

        async openAgentTask(checkpointId: string, grants: string[] = []) {
            return (await request(`/checkpoints/${encodeURIComponent(checkpointId)}/agent-tasks`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ grants }),
            })).json();
        },

        /**
         * Ask the server's configured author to write one role of this task.
         *
         * The editor supplies an instruction and never the source: the bytes
         * come back from the author the deployment configured, and a workspace
         * with none configured is told so rather than shown invented text.
         */
        async proposeAgentEdit(taskId: string, role: string, instruction: string) {
            return (await request(`/agent-tasks/${encodeURIComponent(taskId)}/proposal`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role, instruction }),
            })).json();
        },

        /**
         * Submit one patch against the task that issued its context.
         *
         * `revision` must be the task's own `base_revision`: `apply_agent_patch`
         * re-checks that exact tag under the store lock, so an editor that sent
         * its latest read instead would be naming a revision this task was
         * never scoped to.
         */
        async applyAgentPatch(revision: string, taskId: string, patch: AgentPatch) {
            return (await request(`/agent-tasks/${encodeURIComponent(taskId)}/patch`, {
                method: 'POST',
                headers: withMatch(revision, { 'Content-Type': 'application/json' }),
                body: JSON.stringify(patch),
            })).json();
        },

        /**
         * Build one image per Step through the server's browser runtime.
         *
         * This is a POST, not a link: the request carries the requested export
         * boundaries and a deployment with no browser runtime configured
         * answers PRES_EXPORT_RUNTIME_UNAVAILABLE, which the caller reports
         * rather than presenting an archive nothing captured.
         */
        async exportRaster(groups: string[] | null = null) {
            const response = await request('/exports/raster', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ groups }),
            });
            return {
                archive: await response.blob(),
                revision: response.headers.get('X-Doxagon-Revision'),
                digest: response.headers.get('ETag'),
            };
        },

        exportUrl(format: 'offline-html' | 'source-archive') {
            return `${base}/exports/${format}`;
        },

        assetThumbnailUrl(assetId: string) {
            return `${base}/assets/${encodeURIComponent(assetId)}/thumbnail`;
        },
    };
}

/** The edge a checkpoint registers in each direction, or null where none exists. */
export function edgesFor(deck: DeckPayload | null, checkpointId: string | null): {
    forward: DeckEdge | null;
    reverse: DeckEdge | null;
} {
    if (deck === null || checkpointId === null) return { forward: null, reverse: null };
    return {
        forward: deck.edges.find((edge) => edge.from === checkpointId) ?? null,
        reverse: deck.edges.find((edge) => edge.to === checkpointId) ?? null,
    };
}

/** One run of consecutive Steps that the same slide group holds. */
export interface SlideRun {
    key: string;
    groupId: string | null;
    label: string;
    /**
     * The slide's 1-based place in the deck, or null for Steps no slide claims.
     * A slide that plays in more than one run carries the same number in each.
     */
    number: number | null;
    steps: CheckpointView[];
}

/**
 * The slide-by-slide outline a presenter reads, derived from the stored groups.
 *
 * Runs are cut where the owning slide changes rather than gathered per group,
 * so a group whose Steps are not consecutive in `checkpoint_order` shows up
 * where it actually plays instead of being reordered into one heading.
 */
export function slideOutline(checkpoints: CheckpointView[], groups: GroupView[]): SlideRun[] {
    const slides = new Map(groups.filter((group) => group.kind === 'slide').map((group) => [group.id, group]));
    // Numbered per slide rather than per run, and assigned where the slide is
    // first reached. A reorder can send a deck back to a slide it has already
    // played; counting runs would give that slide a second number and count it
    // twice in the total, so the presenter would read "slide 3 of 3" off a deck
    // holding two slides.
    const numbers = new Map<string, number>();
    const runs: SlideRun[] = [];
    for (const checkpoint of checkpoints) {
        const groupId = checkpoint.groups.find((id) => slides.has(id)) ?? null;
        const open = runs[runs.length - 1];
        if (open !== undefined && open.groupId === groupId) {
            open.steps.push(checkpoint);
            continue;
        }
        if (groupId !== null && !numbers.has(groupId)) numbers.set(groupId, numbers.size + 1);
        runs.push({
            key: `${groupId ?? ''}:${checkpoint.id}`,
            groupId,
            label: groupId === null ? '' : slides.get(groupId)?.label ?? groupId,
            number: groupId === null ? null : numbers.get(groupId) ?? null,
            steps: [checkpoint],
        });
    }
    return runs;
}

/** Move one checkpoint by one position, returning the whole requested order. */
export function movedOrder(order: string[], checkpointId: string, delta: number): string[] {
    const index = order.indexOf(checkpointId);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= order.length) return order;
    const next = [...order];
    next.splice(index, 1);
    next.splice(target, 0, checkpointId);
    return next;
}
