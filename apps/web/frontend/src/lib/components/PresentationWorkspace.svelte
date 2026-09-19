<script lang="ts">
    /**
     * The primary presentation editor and viewer.
     *
     * This is the workspace `/presentations` opens for the presentation the
     * user selected in the project rail. Both authored documents and Step
     * projects use this shell, its responsive regions, and inspector tabs.
     * Authored documents use a read-only adapter and one persistent document
     * player in the canvas. Step projects keep their existing editing client.
     */
    import { onDestroy } from 'svelte';
    import CheckpointPreview from '$lib/components/deck/CheckpointPreview.svelte';
    import ImageViewer from '$lib/components/presentation/ImageViewer.svelte';
    import DocumentPlayer from '$lib/components/presentation/DocumentPlayer.svelte';
    import DocumentInspector from '$lib/components/presentation/DocumentInspector.svelte';
    import { findAuthoredDocument, type AuthoredDocument } from '$lib/presentation/authoredDocument';
    import { readInspection, inspectedSource, type DocumentInspection } from '$lib/presentation/documentInspection';
    import type { DocumentReady, DocumentPosition } from '$lib/presentation/documentBridge';
    import StepAudience from '$lib/components/presentation/StepAudience.svelte';
    import {
        AgentContextError,
        DeckRequestError,
        RETRYABLE_JOB_STATUS,
        agentPatchFor,
        edgesFor,
        migrationOutcome,
        presentationBase,
        presentationClient,
        slideOutline,
        type MigrationOutcome,
        type AgentOutcome,
        type AgentProposal,
        type AgentTask,
        type CheckpointView,
        type DeckPayload,
        type JobView,
        type PresentationClient,
        type Snapshot,
        type StyleView,
        type WorkspaceView,
    } from '$lib/presentation/deck';

    /** The vault presentation this workspace edits. It is the authority. */
    export let presentationSlug: string;
    export let title = '';
    export let documentSource: AuthoredDocument | null = null;
    let documentView: DocumentInspection | null = null;
    let documentPlayer: DocumentPlayer;
    let documentReady: DocumentReady | null = null;
    let documentPosition: DocumentPosition | null = null;
    let documentConnected = false;
    let documentPresenting = false;
    let documentSelected: string | null = null;
    let documentLoad = 0;
    let documentRevisionAvailable = false;
    let checkingDocumentRevision = false;
    let previewWidth = 0;
    let previewHeight = 0;

    async function loadDocumentWorkspace(slug: string, refresh = false) {
        const attempt = ++documentLoad;
        loading = true;
        try {
            const view = await readInspection(slug);
            const source = refresh ? await findAuthoredDocument(slug) : documentSource;
            if (attempt !== documentLoad) return;
            if (!source || source.sha256 !== view.document.sha256) throw new Error('The document selection changed. Refresh the workspace to load its current revision.');
            documentSource = source;
            documentView = view;
            documentRevisionAvailable = false;
            failure = '';
            if (refresh) documentPlayer?.reloadDocument(inspectedSource(view, source), documentPosition?.cue ?? null);
        } catch (error) {
            if (attempt === documentLoad) failure = (error as Error).message;
        } finally { if (attempt === documentLoad) loading = false; }
    }

    function selectDocumentCue(id: string) {
        documentSelected = id;
        documentPlayer?.go(id);
    }

    async function checkDocumentRevision() {
        if (!documentView || documentPresenting || checkingDocumentRevision) return;
        checkingDocumentRevision = true;
        const snapshot = documentView.snapshot;
        try {
            const current = await readInspection(presentationSlug);
            if (documentView?.snapshot === snapshot) documentRevisionAvailable = current.snapshot !== snapshot;
        } catch { /* Explicit refresh reports a pending write or unavailable source. */ }
        finally { checkingDocumentRevision = false; }
    }

    function documentState(event: CustomEvent<{ ready: DocumentReady | null; position: DocumentPosition | null; connected: boolean; presenting: boolean }>) {
        const wasPresenting = documentPresenting;
        documentReady = event.detail.ready;
        documentPosition = event.detail.position;
        documentConnected = event.detail.connected;
        documentPresenting = event.detail.presenting;
        if (wasPresenting && !documentPresenting) void checkDocumentRevision();
    }

    // Product language for the visible surface; the key is the internal
    // contract name the panel ids, test hooks, and API paths keep using. The
    // split is deliberate: renaming a tab must not rename a stored member.
    const TABS = [
        { key: 'overview', label: 'Overview' },
        { key: 'source', label: 'Source' },
        { key: 'edges', label: 'Transitions' },
        { key: 'capabilities', label: 'Permissions' },
        { key: 'groups', label: 'Sections' },
        { key: 'assets', label: 'Media' },
        { key: 'notes', label: 'Notes' },
        { key: 'agent', label: 'Edit with AI' },
    ] as const;
    type Tab = (typeof TABS)[number]['key'];
    // The raw creative sources: arbitrary HTML, CSS, and JavaScript. Notes are
    // authored on their own tab, so they are not offered twice here.
    const SOURCE_ROLES = ['document', 'styles', 'entry'] as const;
    type SourceRole = (typeof SOURCE_ROLES)[number] | 'notes';
    const REGIONS = [
        { key: 'steps', label: 'Steps' },
        { key: 'canvas', label: 'Canvas' },
        { key: 'inspector', label: 'Inspector' },
    ] as const;
    type Region = (typeof REGIONS)[number]['key'];

    /** Product-language count. Media is a mass noun, so it never gains an `s`. */
    const count = (total: number, singular: string, plural = `${singular}s`) =>
        `${total} ${total === 1 ? singular : plural}`;
    // The closed capability vocabulary the server validates against
    // (`src/doxagon/presentations/contracts.py` CAPABILITIES), which is exactly
    // what the realm broker implements. These are protocol symbols, not
    // product copy: the permission a user grants is named by the exact string
    // the broker honours, so it stays verbatim while the surface around it
    // reads "Permissions". Every one is denied until this step's grant lists
    // it, and nothing outside it can be offered: a grant nothing can honour
    // would read as "granted" and do nothing.
    const CAPABILITIES = ['media', 'timers', 'worker'] as const;
    // A section is metadata over steps and never a navigation authority,
    // so it carries a kind and members but no order, cursor, or default.
    const GROUP_KINDS = ['slide', 'section'] as const;
    // Exactly the framings `GenerationSettings` accepts
    // (`src/doxagon/presentations/generation.py` ASPECT_RATIOS). Offering one
    // the settings would refuse would be an authoring control that can only
    // ever produce a refusal.
    const ASPECT_RATIOS = ['16:9', '9:16', '4:3', '3:2', '2:3', '1:1'] as const;

    let client: PresentationClient | null = null;
    let loadedSlug = '';
    let workspace: WorkspaceView | null = null;
    let deck: DeckPayload | null = null;
    let selected: string | null = null;
    let tab: Tab = 'overview';
    let role: SourceRole = 'document';
    let draft = '';
    let notice = '';
    let failure = '';
    // Why this presentation would not open, when the reason is one a person can
    // act on: the list of legacy mapping decisions still outstanding, or the
    // fact that nothing has been authored here yet. It is set only by `load`,
    // because only opening the presentation can answer it.
    let openBlock: MigrationOutcome | null = null;
    let loading = true;
    let busy = false;
    let task: AgentTask | null = null;
    let outcome: AgentOutcome | null = null;
    // A collapsed disclosure still lays its contents out, which paints them
    // outside the inspector on a narrow stacked viewport. Rendering them only
    // while open keeps the closed state a summary and nothing else.
    let showTechnical = false;
    let groupDraftId = '';
    let groupDraftLabel = '';
    let groupDraftKind: (typeof GROUP_KINDS)[number] = 'section';
    let newStepLabel = '';
    let region: Region = 'canvas';
    let stepsCollapsed = false;
    // The image the in-app viewer shows, by asset id. Null keeps it closed.
    let viewing: string | null = null;
    let expandedSlides = new Set<string>();
    let expandedFor = '';
    // Every job this workspace holds, failed ones included: the retry control
    // has to be reachable from the job, because a failed job admitted no asset
    // to hang it off.
    let jobs: JobView[] = [];
    let generationLabel = '';
    let generationAlt = '';
    let generationDescription = '';
    let generationVariants = 1;
    let generationAspect: (typeof ASPECT_RATIOS)[number] = '16:9';
    let generationStyles: string[] = [];
    let editingStyle: string | null = null;
    let styleName = '';
    let styleText = '';
    let styleReferences: string[] = [];
    let instruction = '';
    let proposal: AgentProposal | null = null;
    let session: Snapshot | null = null;
    let presenterWindow: Window | null = null;
    let presenterBlocked = false;
    let presenting = false;

    onDestroy(() => { documentLoad += 1; presenterWindow?.close(); });

    /**
     * Open (or migrate) the selected presentation's Step workspace.
     *
     * Everything this editor shows and mutates is bound to the presentation
     * named here. Changing the selection rebuilds the client, so a mutation
     * can never land in a presentation other than the one on screen.
     */
    async function load(slug: string) {
        const bound = presentationClient(presentationBase(slug));
        client = bound;
        loading = true;
        try {
            const view = await bound.readWorkspace();
            const payload = await bound.readDeck();
            const records = await bound.listJobs();
            if (client !== bound) return;
            workspace = view;
            deck = payload;
            jobs = records;
            generationStyles = generationStyles.filter((id) => view.styles.some((style) => style.id === id));
            if (selected === null || !view.checkpoint_order.includes(selected)) {
                selected = view.checkpoint_order[0] ?? null;
            }
            loadDraft();
            failure = '';
            openBlock = null;
        } catch (error) {
            if (client !== bound) return;
            workspace = null;
            deck = null;
            notice = '';
            // A refusal a person can act on is rendered as itself. Only an
            // opaque one falls back to the code-first developer line, so the
            // structured diagnostics are never reduced to that one sentence.
            openBlock = migrationOutcome(error);
            failure = openBlock === null ? describe(error) : '';
        } finally {
            if (client === bound) loading = false;
        }
    }

    function describe(error: unknown): string {
        if (error instanceof DeckRequestError) return `${error.code}: ${error.message}`;
        // A context the server would refuse is named in the server's own
        // vocabulary, so a refusal reads the same whether the editor or the
        // workspace caught it.
        if (error instanceof AgentContextError) return `${error.code}: ${error.message}`;
        return String((error as Error)?.message ?? error);
    }

    // The notice may only be known once the work has answered — a generation
    // reports the status the job actually finished in — so a caller may pass a
    // thunk the reload result is read through instead of a fixed string.
    async function guard(work: () => Promise<unknown>, message: string | (() => string)) {
        busy = true;
        try {
            await work();
            await load(loadedSlug);
            notice = typeof message === 'function' ? message() : message;
            failure = '';
            return true;
        } catch (error) {
            // A refused mutation leaves the promoted revision untouched, so the
            // editor stays on the revision it read rather than guessing.
            failure = describe(error);
            return false;
        } finally {
            busy = false;
        }
    }

    function openSource(name: string) {
        if (['document', 'styles', 'entry', 'notes'].includes(name)) {
            role = name as SourceRole;
            loadDraft();
        }
    }

    function loadDraft() {
        const source = deck?.checkpoints.find((item) => item.id === selected);
        if (source === undefined) {
            draft = '';
            return;
        }
        draft = role === 'entry' ? source.entry
            : role === 'styles' ? source.styles
            : role === 'notes' ? (source.notes ?? '')
            : source.document;
    }

    function select(checkpointId: string) {
        selected = checkpointId;
        loadDraft();
    }

    /** Track the runtime's own cursor: preview controls are the same authority. */
    function follow(checkpointId: string | null) {
        if (checkpointId === null || checkpointId === selected) return;
        select(checkpointId);
    }

    // Every handler below reads the workspace it was rendered from. Markup
    // expressions are plain JavaScript, so the narrowing has to happen here.
    async function addStep() {
        const current = workspace;
        const bound = client;
        if (busy || current === null || bound === null || newStepLabel.trim() === '') return;
        const label = newStepLabel.trim();
        let added: string | undefined;
        const saved = await guard(async () => {
            const next = await bound.addCheckpoint(current.revision, label, selected);
            added = next.checkpoint_order.find((id) => !current.checkpoint_order.includes(id));
        }, `Step ${label} added`);
        if (saved) {
            newStepLabel = '';
            if (added) select(added);
        }
    }

    function removeStep(item: CheckpointView) {
        const current = workspace;
        const bound = client;
        if (current === null || bound === null) return;
        guard(() => bound.deleteCheckpoint(current.revision, item.id), `Step ${item.label} deleted`);
    }

    function saveLabel(label: string) {
        const current = workspace;
        const bound = client;
        if (current === null || bound === null || checkpoint === null) return;
        const id = checkpoint.id;
        guard(() => bound.relabelCheckpoint(current.revision, id, label), 'Label saved');
    }

    function saveSource() {
        const current = workspace;
        const bound = client;
        if (current === null || bound === null || checkpoint === null) return;
        const id = checkpoint.id;
        const body = draft;
        const target = role;
        guard(() => bound.putSource(current.revision, id, target, body), `Saved ${target}`);
    }

    function toggleAsset(assetId: string) {
        const current = workspace;
        const bound = client;
        if (current === null || bound === null || checkpoint === null) return;
        const held = checkpoint.assets;
        const id = checkpoint.id;
        const next = held.includes(assetId) ? held.filter((item) => item !== assetId) : [...held, assetId];
        guard(
            () => bound.setCheckpointAssets(current.revision, id, next),
            held.includes(assetId) ? 'Removed from this step' : 'Added to this step',
        );
    }

    function removeAsset(assetId: string) {
        const current = workspace;
        const bound = client;
        if (current === null || bound === null) return;
        guard(() => bound.deleteAsset(current.revision, assetId), 'Media deleted');
    }

    function resetStyle() {
        editingStyle = null;
        styleName = '';
        styleText = '';
        styleReferences = [];
    }

    function editStyle(style: StyleView) {
        editingStyle = style.id;
        styleName = style.id;
        styleText = style.text;
        styleReferences = [...style.references];
    }

    async function saveStyle() {
        const current = workspace;
        const bound = client;
        if (current === null || bound === null || busy || !canSaveStyle) return;
        const id = styleName.trim();
        const record = { text: styleText, references: [...styleReferences] };
        if (await guard(() => bound.putStyle(current.revision, id, record), `Style ${id} saved`)) {
            resetStyle();
        }
    }

    async function removeStyle(id: string) {
        const current = workspace;
        const bound = client;
        if (current === null || bound === null || busy) return;
        if (await guard(() => bound.deleteStyle(current.revision, id), `Style ${id} deleted`)) {
            if (editingStyle === id) resetStyle();
        }
    }

    /**
     * Request media for this step and run the job that was recorded.
     *
     * Submitting records what was asked; running produces the bytes. Both
     * happen here because a request nobody executed is not a generation, and
     * the notice reports the status the durable record actually finished in
     * rather than claiming success for work the backend refused.
     */
    function generate() {
        const bound = client;
        if (bound === null || checkpoint === null) return;
        const target = {
            checkpoint_id: checkpoint.id,
            label: generationLabel.trim(),
            alt: generationAlt.trim(),
            description: generationDescription.trim(),
            aspect_ratio: generationAspect,
            variants: generationVariants,
            styles: [...generationStyles],
        };
        let finished = '';
        guard(
            async () => {
                // A fresh key per request: replaying one key is a replay of the
                // same work, which is not what a second Generate click means.
                const job = await bound.startGeneration(newIdempotencyKey(), [target]);
                finished = (await bound.runJob(job.job_id)).status;
            },
            () => `Generation ${finished}`,
        );
    }

    /**
     * Retry exactly one failed job and execute the retry it returned.
     *
     * `JobStore.retry` answers with a new *pending* record, so stopping at the
     * retry call would leave the work the operator asked for unexecuted.
     */
    function retry(job: JobView) {
        const bound = client;
        if (bound === null) return;
        let finished = '';
        guard(
            async () => {
                const scheduled = await bound.retryJob(job.job_id);
                finished = (await bound.runJob(scheduled.job_id)).status;
            },
            () => `Retry ${finished}`,
        );
    }

    /**
     * Build one image per Step and hand the operator the archive.
     *
     * The frames are captured by the server's browser runtime over the closed
     * offline document, so this waits for the real artifact and reports the
     * revision the capturer sealed into it. It deliberately does not go through
     * `guard`: an export promotes nothing, so reloading the workspace would
     * only discard the notice this build has to report. A deployment with no
     * browser runtime answers PRES_EXPORT_RUNTIME_UNAVAILABLE, which is shown
     * as the refusal it is rather than as a build.
     */
    async function buildImages() {
        const bound = client;
        if (bound === null) return;
        busy = true;
        failure = '';
        // A real capture drives a browser over every Step, so the wait is
        // announced through the same live region the outcome will use.
        notice = 'Building images…';
        try {
            const built = await bound.exportRaster();
            save(built.archive, `${presentationSlug}-images.zip`);
            notice = `Images built from ${built.revision ?? 'the current revision'}`;
        } catch (error) {
            notice = '';
            failure = describe(error);
        } finally {
            busy = false;
        }
    }

    /** Hand bytes the server produced to the browser's own download. */
    function save(archive: Blob, filename: string) {
        const href = URL.createObjectURL(archive);
        const anchor = document.createElement('a');
        anchor.href = href;
        anchor.download = filename;
        document.body.append(anchor);
        anchor.click();
        anchor.remove();
        // Revoking in this same task can cancel a download the click only just
        // started, so the object URL is released once that task has finished.
        setTimeout(() => URL.revokeObjectURL(href));
    }

    /** A key no earlier submission can already own. */
    function newIdempotencyKey(): string {
        return `editor-${crypto.randomUUID()}`;
    }

    function toggleCapability(capability: string) {
        const current = workspace;
        const bound = client;
        if (current === null || bound === null || checkpoint === null) return;
        const held = checkpoint.capabilities;
        const id = checkpoint.id;
        const granting = !held.includes(capability);
        const next = granting ? [...held, capability] : held.filter((item) => item !== capability);
        guard(
            () => bound.setCheckpointCapabilities(current.revision, id, next),
            granting ? `Granted ${capability}` : `Revoked ${capability}`,
        );
    }

    /**
     * Opt this step into (or out of) the generated linear transition.
     *
     * The server refuses an edge that is not reversible or that the
     * step's own registration does not declare, so a refused toggle
     * leaves the promoted revision exactly as it was.
     */
    function toggleLinearEdge() {
        const current = workspace;
        const bound = client;
        if (current === null || bound === null || checkpoint === null) return;
        const id = checkpoint.id;
        const next = !linearOptIn;
        guard(
            () => bound.setCheckpointTransition(current.revision, id, next ? { linear: true } : null),
            next ? 'Linear transition opt-in saved' : 'Transition halves retired',
        );
    }

    function saveGroup() {
        const current = workspace;
        const bound = client;
        if (current === null || bound === null || groupDraftId.trim() === '') return;
        const id = groupDraftId.trim();
        const label = groupDraftLabel.trim() || id;
        const kind = groupDraftKind;
        const existing = current.groups.find((group) => group.id === id);
        guard(
            () => bound.putGroup(current.revision, id, {
                kind,
                label,
                checkpoints: existing?.checkpoints ?? [],
                export_boundary: existing?.export_boundary ?? false,
            }),
            existing ? `Section ${id} updated` : `Section ${id} created`,
        );
    }

    function toggleGroupMember(groupId: string) {
        const current = workspace;
        const bound = client;
        if (current === null || bound === null || checkpoint === null) return;
        const group = current.groups.find((item) => item.id === groupId);
        if (group === undefined) return;
        const id = checkpoint.id;
        const holds = group.checkpoints.includes(id);
        const members = holds ? group.checkpoints.filter((item) => item !== id) : [...group.checkpoints, id];
        guard(
            () => bound.putGroup(current.revision, groupId, {
                kind: group.kind,
                label: group.label,
                checkpoints: members,
                export_boundary: group.export_boundary ?? false,
            }),
            holds ? `Removed from ${group.label}` : `Added to ${group.label}`,
        );
    }

    function toggleGroupBoundary(groupId: string) {
        const current = workspace;
        const bound = client;
        if (current === null || bound === null) return;
        const group = current.groups.find((item) => item.id === groupId);
        if (group === undefined) return;
        const next = !(group.export_boundary ?? false);
        guard(
            () => bound.putGroup(current.revision, groupId, {
                kind: group.kind,
                label: group.label,
                checkpoints: group.checkpoints,
                export_boundary: next,
            }),
            next ? `${group.label} is an export boundary` : `${group.label} is no longer an export boundary`,
        );
    }

    function removeGroup(groupId: string) {
        const current = workspace;
        const bound = client;
        if (current === null || bound === null) return;
        guard(() => bound.deleteGroup(current.revision, groupId), `Section ${groupId} deleted`);
    }

    function openTask() {
        const bound = client;
        if (bound === null || checkpoint === null) return;
        const id = checkpoint.id;
        guard(async () => {
            task = await bound.openAgentTask(id);
            outcome = null;
            proposal = null;
        }, 'AI edit opened');
    }

    /**
     * Have the server's author write the proposal a human then approves.
     *
     * The editor sends an instruction and the issued task's id; the bytes come
     * back from the configured authoring backend. This deliberately does not go
     * through `guard`: reloading the workspace would overwrite the draft with
     * the stored source and discard the proposal before anyone could read it.
     * Nothing is promoted here — approval is still a separate, checked patch.
     */
    async function propose() {
        const issued = task;
        const bound = client;
        if (issued === null || bound === null || instruction.trim() === '') return;
        const target = role;
        busy = true;
        try {
            const answer = await bound.proposeAgentEdit(issued.task_id, target, instruction.trim());
            proposal = answer;
            draft = answer.proposal;
            notice = `AI drafted ${answer.role}`;
            failure = '';
        } catch (error) {
            proposal = null;
            failure = describe(error);
        } finally {
            busy = false;
        }
    }

    /**
     * Promote exactly the scoped edit the reviewer approved.
     *
     * The whole patch context — task, base revision, step, and the
     * before-state digest — comes from the issued task, and the If-Match names
     * that task's own base revision, which is the tag `apply_agent_patch`
     * re-checks under the store lock. Nothing here is assembled from the
     * editor's latest read.
     */
    function approve() {
        const issued = task;
        const bound = client;
        if (issued === null || bound === null) return;
        const target = role;
        const body = draft;
        guard(async () => {
            const patch = agentPatchFor(issued, {
                sources: { [target]: body },
                summary: `Agent edit of ${target}`,
            });
            outcome = await bound.applyAgentPatch(issued.base_revision, issued.task_id, patch);
        }, 'AI edit approved and promoted');
    }

    /**
     * Present through the same session this editor's canvas already holds.
     *
     * The presenter window drives that session and this window follows it, so
     * both surfaces read one server-issued cursor over one revision. Nothing
     * is re-fetched, re-pinned, or re-derived for presentation.
     */
    function present() {
        if (session === null) return;
        presenting = true;
        presenterBlocked = false;
        presenterWindow = window.open(
            presenterUrl(session.session_id),
            'presenter',
            'width=1100,height=760,menubar=no,toolbar=no,location=no,status=no',
        );
        // A blocked popup returns null and the audience display would open
        // with no presenter anywhere. Say so, and offer the presenter view as
        // a plain link the person can open themselves.
        if (presenterWindow === null) presenterBlocked = true;
        // The window is named, so a second Present reuses one already open;
        // bring it forward rather than leaving it wherever it was.
        else presenterWindow.focus();
    }

    const presenterUrl = (sessionId: string) =>
        `/present/${encodeURIComponent(presentationSlug)}?session=${encodeURIComponent(sessionId)}`;

    function endPresentation() {
        presenting = false;
        presenterBlocked = false;
        presenterWindow?.close();
        presenterWindow = null;
    }

    /**
     * Retire an issued task the moment the workspace stops showing its scope.
     *
     * A task is scoped to exactly one step (`scope.checkpoint_id`) and pins
     * that step's before-state, while `draft` always holds whatever step is
     * selected now. Every cursor authority moves that selection — the outline,
     * the preview controls the runtime reports through `follow`, and a reload
     * whose step no longer exists — so the invariant is enforced here once
     * rather than at each mover: without it, approving after a move would
     * submit the newly shown step's bytes under the previous step's context.
     */
    $: if (task !== null && task.scope?.checkpoint_id !== selected) {
        task = null;
        outcome = null;
        proposal = null;
    }

    $: if (presentationSlug && presentationSlug !== loadedSlug) {
        loadedSlug = presentationSlug;
        selected = null;
        openBlock = null;
        notice = '';
        session = null;
        presenting = false;
        task = null;
        outcome = null;
        proposal = null;
        generationStyles = [];
        resetStyle();
        if (documentSource) void loadDocumentWorkspace(presentationSlug);
        else void load(presentationSlug);
    }
    $: visibleTabs = documentSource ? TABS.filter(item => ['overview', 'source', 'groups', 'assets', 'notes'].includes(item.key)) : TABS;

    $: checkpoint = workspace?.checkpoints.find((item) => item.id === selected) ?? null;
    $: edges = edgesFor(deck, selected);
    $: directions = [
        { direction: 'forward' as const, edge: edges.forward },
        { direction: 'reverse' as const, edge: edges.reverse },
    ];
    $: assets = workspace?.assets ?? [];
    $: imageAssets = assets.filter((asset) => asset.media_type.startsWith('image/'));
    $: viewingIndex = imageAssets.findIndex((asset) => asset.id === viewing);
    // Revision-pinned original bytes, the same endpoint both galleries render.
    $: assetUrl = (assetId: string) =>
        `${client?.base}/assets/${encodeURIComponent(assetId)}/content?revision=${encodeURIComponent(workspace?.revision ?? '')}`;
    $: styles = workspace?.styles ?? [];
    $: duplicateStyle = editingStyle === null && styles.some((style) => style.id === styleName.trim());
    $: canSaveStyle = /^[a-z][a-z0-9_-]{0,63}$/.test(styleName.trim())
        && styleText.trim() !== '' && !duplicateStyle;
    $: declared = new Set(checkpoint?.assets ?? []);
    $: granted = new Set(checkpoint?.capabilities ?? []);
    $: groups = workspace?.groups ?? [];
    $: steps = workspace?.checkpoints ?? [];
    $: slideRuns = slideOutline(steps, workspace?.groups ?? []);
    $: activeRunKey = slideRuns.find((run) => run.steps.some((step) => step.id === selected))?.key;
    $: if (`${selected}:${activeRunKey}` !== expandedFor) {
        expandedFor = `${selected}:${activeRunKey}`;
        if (activeRunKey) expandedSlides = new Set([...expandedSlides, activeRunKey]);
    }

    function toggleSlide(key: string) {
        const next = new Set(expandedSlides);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        expandedSlides = next;
    }
    $: linearOptIn = Boolean(
        deck?.edges.some((edge) => edge.generated && (edge.from === selected || edge.to === selected)),
    );
    $: canGenerate = generationLabel.trim() !== ''
        && generationAlt.trim() !== ''
        && generationDescription.trim() !== '';

    const groupLabel = (id: string) => workspace?.groups.find((group) => group.id === id)?.label ?? id;
</script>

<svelte:window on:focus={() => checkDocumentRevision()} />
<div class="presentation-editor" class:authored-workspace={!!documentSource} class:document-presenting={documentPresenting} data-presentation={presentationSlug}>
    <header class="editor-chrome">
        <div class="chrome-title">
            <p class="chrome-mark">Presentation</p>
            <h2>{title || presentationSlug}</h2>
        </div>
        <div class="chrome-actions" role="toolbar" aria-label="Presentation actions">
            {#if openBlock === null}
            <button
                type="button"
                class="primary"
                data-testid="present"
                disabled={documentSource ? !documentConnected : session === null}
                on:click={() => documentSource ? documentPlayer?.present() : present()}
            ><span aria-hidden="true">▶</span> Present</button>
            {/if}
            {#if documentSource}
                <button type="button" disabled={loading || documentPresenting} on:click={() => loadDocumentWorkspace(presentationSlug, true)}>Refresh document</button>
                {#if documentRevisionAvailable}<span role="status">A new revision is available. Refresh when ready.</span>{/if}
            {/if}
            {#if client && openBlock === null}
                <a class="chrome-link" data-testid="export-offline" href={client.exportUrl('offline-html')} download>
                    Build offline HTML
                </a>
                <a class="chrome-link" data-testid="export-sources" href={client.exportUrl('source-archive')} download>
                    Export sources
                </a>
                <button
                    type="button"
                    class="chrome-action"
                    data-testid="export-raster"
                    disabled={busy || workspace === null}
                    on:click={buildImages}
                >Build images</button>
            {/if}
        </div>
        <details class="workspace-details" data-advanced="true"><summary>Presentation details</summary><dl class="chrome-identity">
            <dt>Revision</dt>
            <dd data-testid="deck-revision">{documentView?.document.sha256 ?? workspace?.revision ?? '—'}</dd>
            <dt>Runtime</dt>
            <dd data-testid="deck-runtime">{documentReady ? `${documentReady.documentId} · ${documentReady.edition}` : deck?.runtime_version ?? '—'}</dd>
        </dl></details>
    </header>

    {#if failure}
        <p class="editor-failure" role="alert" data-testid="deck-failure">
            <span>This action did not complete.</span>
            <!-- The refusal is reported in the server's own vocabulary, code
                 first, so an operator can match it to the contract that
                 raised it. That is developer detail, not product copy. -->
            <code data-advanced="true">{failure}</code>
        </p>
    {:else if notice}
        <p class="editor-notice" role="status" data-testid="deck-notice">{notice}</p>
    {/if}

    {#if openBlock === null}
        <nav class="region-switch" aria-label="Workspace region">
            {#each REGIONS as item}
                <button
                    type="button"
                    class:active={region === item.key}
                    aria-pressed={region === item.key}
                    on:click={() => (region = item.key)}
                >{item.label}</button>
            {/each}
        </nav>
    {/if}

    {#if openBlock?.kind === 'empty'}
        <!-- Nothing is wrong here: this project simply has no presentation. -->
        <section class="presentation-empty" role="status" data-testid="presentation-empty">
            <p class="panel-mark">Presentation</p>
            <h3>This project has no presentation yet</h3>
            <p>Once a first slide is written for this project, it opens here.</p>
        </section>
    {:else if openBlock?.kind === 'blocked'}
        <!-- Every diagnostic the refusal published, one row each, grouped by
             the slide or file the producer located it against. The internal
             code stays visible as secondary detail so a report can name it. -->
        <section class="migration-blockers" role="status" data-testid="migration-blockers">
            <p class="panel-mark">Presentation</p>
            <h3>This presentation cannot be opened yet</h3>
            <p class="blockers-lead">
                {count(openBlock.total, 'item')} still {openBlock.total === 1 ? 'needs' : 'need'} a person to decide
                what this presentation should say. Nothing in the project has been changed.
            </p>
            {#each openBlock.groups as subject (subject.subject)}
                <article class="blocker-subject" data-subject={subject.subject}>
                    <h4>{subject.kind === 'slide' ? `Slide ${subject.subject}` : subject.subject}</h4>
                    <ul>
                        {#each subject.blockers as blocker}
                            <li class="blocker" data-code={blocker.code}>
                                <p class="blocker-summary">{blocker.summary}</p>
                                <p class="blocker-detail" data-advanced="true">
                                    <code>{blocker.code}</code>
                                    <span>{blocker.detail}</span>
                                    {#if blocker.location}<span class="blocker-location">{blocker.location}</span>{/if}
                                </p>
                            </li>
                        {/each}
                    </ul>
                </article>
            {/each}
        </section>
    {:else if loading && workspace === null && documentView === null}
        <p class="editor-state" role="status">Opening the presentation workspace…</p>
    {:else if workspace === null && documentView === null && !documentSource}
        <p class="editor-state" role="status">This presentation has no Step workspace to open.</p>
    {:else}
        <div
            class="editor-body"
            class:steps-collapsed={stepsCollapsed}
            class:show-steps={region === 'steps'}
            class:show-canvas={region === 'canvas'}
            class:show-inspector={region === 'inspector'}
        >
            <nav class="outline" aria-label="Step order"><button class="steps-toggle" type="button" aria-label={stepsCollapsed ? 'Expand steps' : 'Collapse steps'} aria-expanded={!stepsCollapsed} on:click={() => stepsCollapsed = !stepsCollapsed}>{stepsCollapsed ? '☰' : 'Steps ‹'}</button>
                {#if documentSource}
                    <div class="outline-list" data-testid="document-outline">
                        <p class="hint">Chapters and cues</p>
                        <ol>
                            {#each documentReady?.cues ?? documentView?.cues ?? [] as cue, index}
                                <li class="outline-item" class:is-selected={documentSelected === cue.id}>
                                    <button type="button" class="outline-select" aria-current={documentSelected === cue.id ? 'true' : 'false'} disabled={!documentConnected} title={cue.title} on:click={() => selectDocumentCue(cue.id)}><span class="outline-index">{index + 1}</span><span class="outline-label">{cue.title}</span></button>
                                </li>
                            {/each}
                        </ol>
                    </div>
                {:else}
                <div class="outline-add">
                    <label class="label-field">
                        <span>New step</span>
                        <input
                            type="text"
                            data-testid="new-step-label"
                            placeholder="Name a blank step"
                            bind:value={newStepLabel}
                            on:keydown={(event) => { if (event.key === 'Enter') addStep(); }}
                        />
                    </label>
                    <button
                        type="button"
                        class="primary"
                        data-testid="add-step"
                        disabled={busy || newStepLabel.trim() === ''}
                        on:click={addStep}
                    >Add step</button>
                </div>
                <p class="hint add-hint">Adds a blank step after the current one.</p>
                <div class="outline-list" data-testid="checkpoint-outline">
                    {#each slideRuns as run (run.key)}
                        {@const grouped = run.number !== null && run.steps.length > 1}
                        <div class="slide-run" class:is-active={run.steps.some((item) => item.id === selected)} data-slide={run.groupId}>
                            {#if grouped}
                                <button
                                    type="button"
                                    class="slide-toggle"
                                    title={`Slide ${run.number}: ${run.label}`}
                                    aria-label={`Slide ${run.number}: ${run.label}`}
                                    aria-expanded={expandedSlides.has(run.key)}
                                    aria-controls={`slide-run-${run.key}`}
                                    on:click={() => toggleSlide(run.key)}
                                >
                                    <span aria-hidden="true">{expandedSlides.has(run.key) ? '▾' : '▸'}</span>
                                    <span class="outline-label">{run.number}. {run.label}</span>
                                    <span class="slide-count">{run.steps.length}</span>
                                </button>
                            {/if}
                            <ol id={`slide-run-${run.key}`} class:reveal-steps={grouped} hidden={grouped && !expandedSlides.has(run.key)}>
                                {#each run.steps as item (item.id)}
                                    <li class="outline-item" class:is-selected={item.id === selected}>
                                        <button
                                            type="button"
                                            class="outline-select"
                                            title={item.label}
                                            aria-current={item.id === selected ? 'true' : 'false'}
                                            data-checkpoint={item.id}
                                            on:click={() => select(item.id)}
                                        >
                                            <span class="outline-index">{item.index + 1}</span>
                                            <span class="outline-label">{item.label}</span>
                                        </button>
                                    </li>
                                {/each}
                            </ol>
                        </div>
                    {/each}
                </div>
                {/if}
            </nav>

            <section class="stage" aria-label={documentSource ? 'Selected document' : 'Selected step'}>
                {#if documentSource}
                    <p class="hint">Preview viewport · {Math.round(previewWidth)} × {Math.round(previewHeight)} px</p>
                    <div class="document-canvas">
                        <DocumentPlayer bind:this={documentPlayer} bind:viewportWidth={previewWidth} bind:viewportHeight={previewHeight} source={documentView ? inspectedSource(documentView, documentSource) : { ...documentSource, notesUrl: null }} embedded on:state={documentState} />
                    </div>
                {:else}
                {#if checkpoint}
                    <label class="label-field">
                        <span>Label</span>
                        <input
                            type="text"
                            value={checkpoint.label}
                            data-testid="checkpoint-label"
                            on:change={(event) => saveLabel(event.currentTarget.value)}
                        />
                    </label>
                {/if}
                {#if client}
                    <CheckpointPreview
                        {client}
                        {deck}
                        checkpointId={selected}
                        on:state={(event) => follow(event.detail.checkpointId)}
                        on:session={(event) => (session = event.detail)}
                    />
                {/if}
                {/if}
            </section>

            <section class="inspector" aria-label="Step inspector"><h3 class="region-heading">Presentation data</h3>
                <div class="tablist" role="tablist" aria-label="Step inspector tabs">
                    {#each visibleTabs as { key, label }}
                        <button
                            type="button"
                            role="tab"
                            id={`tab-${key}`}
                            aria-selected={tab === key}
                            aria-controls={`panel-${key}`}
                            on:click={() => { tab = key; if (key === 'notes') { role = 'notes'; loadDraft(); } else if (key === 'source' && role === 'notes') { role = 'document'; loadDraft(); } }}
                        >{label}</button>
                    {/each}
                </div>

                {#if documentView && loading}
                    <p role="status">Refreshing inspection…</p>
                {:else if documentView}
                    <DocumentInspector view={documentView} bind:tab ready={documentReady} currentCue={documentPosition?.cue ?? null} />
                {:else if documentSource}
                    <p class="hint">Inspection is unavailable for this revision. The selected HTML remains available in the canvas. Refresh to retry inspection.</p>
                {:else if tab === 'overview'}
                    <div class="panel" role="tabpanel" id="panel-overview" aria-labelledby="tab-overview">
                        <p class="hint">{steps.length} steps · {assets.length} media files · {styles.length} saved image styles</p>
                        <h3 class="panel-heading">{checkpoint?.label ?? 'Selected step'}</h3>
                        <p class="hint">Browse the images below. Source shows the step’s HTML or XML markup, CSS (including imports), and JavaScript. Media includes image details, saved styles, and generation history.</p>
                        <div class="source-catalogue">
                            {#each checkpoint?.sources ?? [] as source}
                                <button type="button" on:click={() => { tab = source.role === 'notes' ? 'notes' : 'source'; openSource(source.role); }}>
                                    <strong>{source.role === 'document' ? 'HTML / XML' : source.role === 'styles' ? 'CSS / imports' : source.role === 'entry' ? 'JavaScript' : 'Notes'}</strong>
                                    <code>{source.path}</code>
                                </button>
                            {/each}
                        </div>
                        <h3 class="panel-heading">All presentation images</h3>
                        <ul class="overview-gallery">
                            {#each imageAssets as asset (asset.id)}
                                <li>
                                    <button type="button" class="image-open" title={`View ${asset.label}`} on:click={() => (viewing = asset.id)}>
                                        <img src={assetUrl(asset.id)} alt={asset.alt || asset.label} loading="lazy" />
                                    </button>
                                    <strong>{asset.label}</strong>
                                    <small>{asset.referenced_by.length ? `Used in ${asset.referenced_by.length} step(s)` : 'Unused candidate'}{declared.has(asset.id) ? ' · In current step' : ''}</small>
                                </li>
                            {:else}
                                <li class="hint">No images in this presentation.</li>
                            {/each}
                        </ul>
                    </div>
                {:else if tab === 'source'}
                    <div class="panel" role="tabpanel" id="panel-source" aria-labelledby="tab-source">
                        <div class="role-switch" role="group" aria-label="Source file">
                            {#each SOURCE_ROLES as name}
                                <button
                                    type="button"
                                    aria-pressed={role === name}
                                    data-role={name}
                                    on:click={() => { role = name; loadDraft(); }}
                                >{name === 'document' ? 'HTML / XML' : name === 'styles' ? 'CSS / imports' : 'JavaScript'}</button>
                            {/each}
                        </div>
                        <textarea
                            aria-label={`Raw ${role} source`}
                            data-testid="source-editor"
                            spellcheck="false"
                            wrap="off"
                            bind:value={draft}
                        ></textarea>
                        <button
                            type="button"
                            class="primary"
                            disabled={busy || checkpoint === null}
                            on:click={saveSource}
                        >Validate and promote</button>
                        {#if checkpoint}
                            <button type="button" disabled={busy || steps.length < 2} aria-label={`Delete ${checkpoint.label}`} on:click={() => checkpoint && removeStep(checkpoint)}>Delete this step</button>
                        {/if}
                        <!-- Registered paths, digests, and the stable identifier
                             are the storage contract, so they are named here in
                             contract vocabulary behind an explicit developer
                             disclosure rather than in the product surface. -->
                        <details class="advanced" data-advanced="true" data-testid="source-technical" bind:open={showTechnical}>
                            <summary>Technical details</summary>
                            {#if showTechnical}
                                <p class="hint">Checkpoint ID <code>{checkpoint?.id ?? '—'}</code></p>
                                <ul class="digests">
                                    {#each checkpoint?.sources ?? [] as source}
                                        <li><code>{source.role}</code> {source.path} · {source.sha256.slice(0, 12)} · {source.bytes} B</li>
                                    {/each}
                                </ul>
                            {/if}
                        </details>
                    </div>
                {:else if tab === 'notes'}
                    <div class="panel" role="tabpanel" id="panel-notes" aria-labelledby="tab-notes" data-testid="notes-panel">
                        <p class="hint">Presenter notes travel with this step's other sources in the same revision.</p>
                        <textarea
                            aria-label="Presenter notes"
                            data-testid="notes-editor"
                            bind:value={draft}
                        ></textarea>
                        <button
                            type="button"
                            class="primary"
                            data-testid="save-notes"
                            disabled={busy || checkpoint === null}
                            on:click={saveSource}
                        >Save notes</button>
                    </div>
                {:else if tab === 'edges'}
                    <div class="panel" role="tabpanel" id="panel-edges" aria-labelledby="tab-edges" data-testid="edge-panel">
                        <p class="hint">
                            A transition joins two steps and must be reversible. Next and Back traverse
                            the halves of a registered transition; there is no index to fall through to.
                        </p>
                        <div class="edge-controls">
                            <label class="toggle">
                                <input
                                    type="checkbox"
                                    data-testid="edge-linear"
                                    checked={linearOptIn}
                                    disabled={busy || checkpoint === null}
                                    on:change={toggleLinearEdge}
                                />
                                <span>Opt into the generated linear transition</span>
                            </label>
                        </div>
                        {#each directions as { direction, edge } (direction)}
                            <article class="edge">
                                <h3>{direction}</h3>
                                {#if edge}
                                    <dl>
                                        <dt>Transition</dt><dd data-testid={`edge-${direction}-id`}>{edge.id}</dd>
                                        <dt>From</dt><dd>{edge.from}</dd>
                                        <dt>To</dt><dd>{edge.to}</dd>
                                        <dt>Duration</dt><dd>{edge.duration_ms ?? '—'}</dd>
                                        <dt>Generated</dt><dd>{edge.generated ? 'linear opt-in' : 'declared'}</dd>
                                    </dl>
                                    <button type="button" on:click={() => select(direction === 'forward' ? edge.to : edge.from)}>
                                        Preview {direction === 'forward' ? edge.to : edge.from}
                                    </button>
                                {:else}
                                    <p class="empty">No registered {direction} transition.</p>
                                {/if}
                            </article>
                        {/each}
                    </div>
                {:else if tab === 'capabilities'}
                    <div class="panel" role="tabpanel" id="panel-capabilities" aria-labelledby="tab-capabilities">
                        <p class="hint">
                            Every permission is denied until this step is granted it. Revoking one
                            a program still requests is refused, so the grant is the authority.
                        </p>
                        <ul data-testid="capability-list">
                            {#each CAPABILITIES as capability}
                                <li>
                                    <label class="toggle">
                                        <input
                                            type="checkbox"
                                            data-capability={capability}
                                            checked={granted.has(capability)}
                                            disabled={busy || checkpoint === null}
                                            on:change={() => toggleCapability(capability)}
                                        />
                                        <span>{capability}</span>
                                        <span class="badge" class:is-empty={!granted.has(capability)}>
                                            {granted.has(capability) ? 'granted' : 'denied'}
                                        </span>
                                    </label>
                                </li>
                            {/each}
                        </ul>
                    </div>
                {:else if tab === 'groups'}
                    <div class="panel" role="tabpanel" id="panel-groups" aria-labelledby="tab-groups" data-testid="group-panel">
                        <p class="hint">
                            Sections label related steps, such as “Introduction” or “Demo”. Enter a short ID (for example, intro) and a label, then save. Select a step and use “Add here” to include it. Use kind “slide” for the reveal steps of one slide, or “section” for a topic spanning slides. Export boundary marks the section for export tools. You can leave sections alone when browsing; they do not change playback order.
                        </p>
                        <div class="group-form">
                            <label class="label-field">
                                <span>Section id</span>
                                <input type="text" data-testid="group-id" bind:value={groupDraftId} />
                            </label>
                            <label class="label-field">
                                <span>Label</span>
                                <input type="text" data-testid="group-label" bind:value={groupDraftLabel} />
                            </label>
                            <label class="label-field">
                                <span>Kind</span>
                                <select data-testid="group-kind" bind:value={groupDraftKind}>
                                    {#each GROUP_KINDS as kind}<option value={kind}>{kind}</option>{/each}
                                </select>
                            </label>
                            <button
                                type="button"
                                class="primary"
                                data-testid="group-save"
                                disabled={busy || groupDraftId.trim() === ''}
                                on:click={saveGroup}
                            >Save section</button>
                        </div>
                        <ul data-testid="group-list">
                            {#each groups as group (group.id)}
                                <li class="group-row" data-group={group.id}>
                                    <!-- The stored identifier `/groups/{id}` addresses, shown
                                         verbatim so an author can name this section again in
                                         the form above. The migrator mints it in contract
                                         vocabulary, so it is marked developer detail for the
                                         same reason a refusal code is. -->
                                    <span class="group-name">{group.label} <code data-advanced="true">{group.id}</code></span>
                                    <span class="group-meta">{group.kind} · {count(group.checkpoints.length, 'step')}</span>
                                    <span class="group-actions">
                                        <button
                                            type="button"
                                            aria-pressed={group.checkpoints.includes(checkpoint?.id ?? '')}
                                            disabled={busy || checkpoint === null}
                                            on:click={() => toggleGroupMember(group.id)}
                                        >{group.checkpoints.includes(checkpoint?.id ?? '') ? 'Remove here' : 'Add here'}</button>
                                        <button
                                            type="button"
                                            aria-pressed={group.export_boundary ?? false}
                                            disabled={busy}
                                            on:click={() => toggleGroupBoundary(group.id)}
                                        >{group.export_boundary ? 'Export boundary' : 'Not an export boundary'}</button>
                                        <button
                                            type="button"
                                            disabled={busy}
                                            on:click={() => removeGroup(group.id)}
                                        >Delete</button>
                                    </span>
                                </li>
                            {:else}
                                <li class="empty">This revision declares no section.</li>
                            {/each}
                        </ul>
                    </div>
                {:else if tab === 'assets'}
                    <div class="panel" role="tabpanel" id="panel-assets" aria-labelledby="tab-assets">
                        <p class="hint">
                            All images and other media in this presentation, including unused candidates. Select an image to view it at full size. “Use in this step” makes it available to the step’s source; the source controls how it appears.
                        </p>
                        <ul class="asset-grid" data-testid="asset-grid">
                            {#each assets as asset (asset.id)}
                                <li class="asset" data-asset={asset.id}>
                                    {#if asset.media_type.startsWith('image/')}
                                        <button type="button" class="image-open" title={`View ${asset.label}`} on:click={() => (viewing = asset.id)}>
                                            <img class="asset-preview" src={assetUrl(asset.id)} alt={asset.alt || asset.label} loading="lazy" />
                                        </button>
                                    {/if}
                                    <h3>{asset.label}</h3>
                                    <p class="asset-alt">{asset.alt ?? 'no alt text'}</p>
                                    <dl>
                                        <dt>Origin</dt><dd>{asset.provenance.kind}</dd>
                                        <dt>Generator</dt><dd>{asset.provenance.generator ?? '—'}</dd>
                                        <dt>Digest</dt><dd>{asset.sha256.slice(0, 12)}</dd>
                                        <dt>Job</dt>
                                        <dd data-testid={`asset-status-${asset.id}`}>
                                            {asset.generation ? `${asset.generation.status} · ${asset.generation.job_id}` : 'not generated here'}
                                        </dd>
                                        <dt>Variant</dt>
                                        <dd>{asset.generation?.variant_index ?? '—'}</dd>
                                        <dt>Used by</dt>
                                        <dd>{asset.referenced_by.length ? asset.referenced_by.join(', ') : 'no step'}</dd>
                                        {#if styles.some((style) => style.references.includes(asset.id))}
                                            <dt>Style references</dt>
                                            <dd>{styles.filter((style) => style.references.includes(asset.id)).map((style) => style.id).join(', ')}</dd>
                                        {/if}
                                    </dl>
                                    <div class="asset-actions">
                                        <button
                                            type="button"
                                            disabled={busy || checkpoint === null}
                                            aria-pressed={declared.has(asset.id)}
                                            on:click={() => toggleAsset(asset.id)}
                                        >{declared.has(asset.id) ? 'Stop using here' : 'Use in this step'}</button>
                                        <button
                                            type="button"
                                            disabled={busy || asset.referenced_by.length > 0 || styles.some((style) => style.references.includes(asset.id))}
                                            on:click={() => removeAsset(asset.id)}
                                        >Delete</button>
                                    </div>
                                </li>
                            {:else}
                                <li class="empty">This revision declares no media.</li>
                            {/each}
                        </ul>

                        <section class="image-styles" aria-labelledby="image-styles-heading">
                            <h3 class="panel-heading" id="image-styles-heading">Image styles</h3>
                            <p class="hint">Save a visual direction and reference images to reuse when generating media for this presentation.</p>
                            <ul data-testid="style-list">
                                {#each styles as style (style.id)}
                                    <li class="style-row" data-style={style.id}>
                                        <h4>{style.id}</h4>
                                        <p class="style-text">{style.text}</p>
                                        {#if style.references.length}
                                            <p class="hint">References: {style.references.map((id) => assets.find((item) => item.id === id)?.label ?? id).join(', ')}</p>
                                        {/if}
                                        <div class="group-actions">
                                            <button type="button" disabled={busy} on:click={() => editStyle(style)}>Edit</button>
                                            <button type="button" disabled={busy} on:click={() => removeStyle(style.id)}>Delete</button>
                                        </div>
                                    </li>
                                {:else}
                                    <li class="empty">No image styles saved yet.</li>
                                {/each}
                            </ul>
                            <form class="style-form" on:submit|preventDefault={saveStyle}>
                                <h4>{editingStyle === null ? 'New image style' : `Edit ${editingStyle}`}</h4>
                                <label class="label-field">
                                    <span>Style name</span>
                                    <input type="text" bind:value={styleName} disabled={busy || editingStyle !== null} aria-describedby="style-name-hint" />
                                </label>
                                <p class="hint" id="style-name-hint">Start with a lowercase letter; use lowercase letters, numbers, hyphens, or underscores. Up to 64 characters.</p>
                                {#if duplicateStyle}
                                    <p class="hint">A style with this name already exists. Choose Edit to change it.</p>
                                {/if}
                                <label class="label-field">
                                    <span>Style prompt</span>
                                    <textarea bind:value={styleText} disabled={busy}></textarea>
                                </label>
                                <fieldset class="style-choices" disabled={busy}>
                                    <legend>Reference images</legend>
                                    {#each assets as asset (asset.id)}
                                        <label class="toggle">
                                            <input type="checkbox" value={asset.id} bind:group={styleReferences} />
                                            <span>{asset.label}</span>
                                        </label>
                                    {:else}
                                        <p class="hint">No media available for reference.</p>
                                    {/each}
                                </fieldset>
                                <div class="group-actions">
                                    <button type="submit" class="primary" disabled={busy || !canSaveStyle}>Save style</button>
                                    <button type="button" disabled={busy} on:click={resetStyle}>Cancel</button>
                                </div>
                            </form>
                        </section>

                        <h3 class="panel-heading">Generate media</h3>
                        <p class="hint">
                            Every variant a generation produces is admitted as its own equal media
                            item. A step uses one only once you say so here.
                        </p>
                        <div class="generation-form">
                            {#if styles.length}
                                <fieldset class="style-choices" disabled={busy}>
                                    <legend>Styles for this generation</legend>
                                    {#each styles as style (style.id)}
                                        <label class="toggle">
                                            <input type="checkbox" value={style.id} bind:group={generationStyles} />
                                            <span>{style.id}</span>
                                        </label>
                                    {/each}
                                </fieldset>
                            {/if}
                            <label class="label-field">
                                <span>Label</span>
                                <input type="text" data-testid="generation-label" bind:value={generationLabel} />
                            </label>
                            <label class="label-field">
                                <span>Alt text</span>
                                <input type="text" data-testid="generation-alt" bind:value={generationAlt} />
                            </label>
                            <label class="label-field">
                                <span>Visual description</span>
                                <textarea data-testid="generation-description" bind:value={generationDescription}></textarea>
                            </label>
                            <label class="label-field">
                                <span>Framing</span>
                                <select data-testid="generation-aspect" bind:value={generationAspect}>
                                    {#each ASPECT_RATIOS as ratio}<option value={ratio}>{ratio}</option>{/each}
                                </select>
                            </label>
                            <label class="label-field">
                                <span>Variants</span>
                                <input
                                    type="number"
                                    min="1"
                                    max="8"
                                    data-testid="generation-variants"
                                    bind:value={generationVariants}
                                />
                            </label>
                            <button
                                type="button"
                                class="primary"
                                data-testid="generate"
                                disabled={busy || checkpoint === null || !canGenerate}
                                on:click={generate}
                            >Generate media</button>
                        </div>

                        <h3 class="panel-heading">Generation history</h3>
                        <ul data-testid="job-list">
                            {#each jobs as job (job.job_id)}
                                <li class="job-row" data-job={job.job_id} data-status={job.status}>
                                    <span class="job-name">{job.kind} · attempt {job.attempt}</span>
                                    <span class="job-meta" data-testid={`job-status-${job.job_id}`}>{job.status}</span>
                                    {#if job.error}
                                        <!-- The backend's own refusal, verbatim: a paraphrase
                                             could not be matched to the record that raised it. -->
                                        <code class="job-error" data-advanced="true">{job.error.code}: {job.error.message}</code>
                                    {/if}
                                    {#each job.failures as item}
                                        <code class="job-error" data-advanced="true">{item.code}: {item.message}</code>
                                    {/each}
                                    {#if job.status === RETRYABLE_JOB_STATUS}
                                        <button
                                            type="button"
                                            data-testid={`retry-${job.job_id}`}
                                            disabled={busy}
                                            on:click={() => retry(job)}
                                        >Retry</button>
                                    {/if}
                                </li>
                            {:else}
                                <li class="empty">Nothing has been generated in this workspace.</li>
                            {/each}
                        </ul>
                    </div>
                {:else}
                    <div class="panel" role="tabpanel" id="panel-agent" aria-labelledby="tab-agent" data-testid="agent-panel">
                        <p class="hint">An AI edit is scoped to exactly one step and its declared context.</p>
                        <button
                            type="button"
                            disabled={busy || checkpoint === null}
                            on:click={openTask}
                        >Edit {checkpoint?.id ?? '—'} with AI</button>
                        {#if task}
                            <dl data-testid="agent-context">
                                <dt>Request</dt><dd data-testid="agent-task">{task.task_id}</dd>
                                <dt>Step</dt><dd data-testid="agent-scope">{task.scope?.checkpoint_id ?? '—'}</dd>
                                <dt>Base revision</dt><dd data-testid="agent-base-revision">{task.base_revision}</dd>
                                <dt>Before digest</dt>
                                <dd data-testid="agent-before-digest">{task.before_digest ?? '—'}</dd>
                                <dt>Before preview</dt>
                                <dd data-testid="agent-before-preview">{task.before?.preview?.preview_sha256 ?? '—'}</dd>
                                <dt>Writable</dt>
                                <dd data-testid="agent-editable">
                                    {(task.scope?.editable_sources ?? []).map((item) => item.role).join(', ') || 'nothing'}
                                </dd>
                            </dl>
                            {#if task.stale}
                                <p class="editor-failure" role="alert" data-testid="agent-stale">
                                    This AI edit was issued against an older revision; re-open it before approving.
                                </p>
                            {/if}
                            <label class="label-field">
                                <span>What should the AI change?</span>
                                <textarea
                                    data-testid="agent-instruction"
                                    bind:value={instruction}
                                    aria-label="Instruction for the AI"
                                ></textarea>
                            </label>
                            <button
                                type="button"
                                data-testid="agent-propose"
                                disabled={busy || task.stale === true || instruction.trim() === ''}
                                on:click={propose}
                            >Draft {role} with AI</button>
                            {#if proposal}
                                <dl data-testid="agent-proposal">
                                    <dt>Written by</dt><dd data-testid="agent-proposal-author">{proposal.author}</dd>
                                    <dt>Source</dt><dd data-testid="agent-proposal-role">{proposal.role}</dd>
                                    <dt>Proposed digest</dt>
                                    <dd data-testid="agent-proposal-digest">{proposal.proposal_sha256.slice(0, 12)}</dd>
                                </dl>
                            {/if}
                            <label class="label-field">
                                <span>Proposed {role}</span>
                                <textarea data-testid="agent-draft" bind:value={draft} aria-label="Proposed source"></textarea>
                            </label>
                            <button
                                type="button"
                                class="primary"
                                disabled={busy || task.stale === true}
                                on:click={approve}
                            >Approve and promote</button>
                        {/if}
                        {#if outcome}
                            <dl data-testid="agent-outcome">
                                <dt>Before</dt><dd data-testid="agent-outcome-before">{outcome.base_revision}</dd>
                                <dt>After</dt><dd data-testid="agent-outcome-after">{outcome.revision}</dd>
                                <dt>Before preview</dt>
                                <dd data-testid="agent-outcome-before-preview">{outcome.diff.preview.before}</dd>
                                <dt>After preview</dt>
                                <dd data-testid="agent-outcome-after-preview">{outcome.diff.preview.after}</dd>
                            </dl>
                            <!-- Registered file paths are the storage contract. -->
                            <ul class="agent-diff" data-advanced="true" data-testid="agent-diff">
                                {#each outcome.diff.sources as row (row.path)}
                                    <li data-source={row.role}>
                                        {row.role} · {row.path} · {row.changed ? 'changed' : 'unchanged'}
                                    </li>
                                {/each}
                            </ul>
                        {/if}
                    </div>
                {/if}
            </section>
        </div>
    {/if}

    {#if presenting && session !== null && client !== null}
        <StepAudience
            {client}
            {deck}
            sessionId={session.session_id}
            presenterUrl={presenterBlocked ? presenterUrl(session.session_id) : null}
            on:close={endPresentation}
        />
    {/if}
    {#if viewing !== null && viewingIndex >= 0}
        <ImageViewer images={imageAssets} index={viewingIndex} urlFor={assetUrl} on:close={() => (viewing = null)} />
    {/if}
</div>

<style>
    @media (max-width: 1023px) {
        /* Keep the authored viewport laid out while another region is shown.
           display:none changes its scroll geometry and can discard its cue. */
        .authored-workspace .editor-body { position: relative; }
        .authored-workspace .editor-body:not(.show-canvas) .stage {
            display: block; position: absolute; inset: 0 0 auto;
            visibility: hidden; pointer-events: none;
        }
        .authored-workspace.document-presenting .editor-body .stage { visibility: visible; pointer-events: auto; }
    }
    .document-presenting > .editor-chrome, .document-presenting > .region-switch,
    .document-presenting .outline, .document-presenting .inspector { visibility: hidden; }
    .document-presenting .editor-body { container-type: normal; }
    .document-presenting .editor-body .stage { display: block; }
    /* The app shell owns the viewport. This workspace fills exactly the space
       the shell gives it — `height: 100%`, `min-height: 0`, scoped overflow —
       so nothing here double-counts viewport height under the global header. */
    .presentation-editor {
        display: grid;
        grid-template-rows: auto auto auto minmax(0, 1fr);
        gap: 0.75rem;
        height: 100%;
        min-height: 0;
        min-width: 0;
        padding: 1rem;
        box-sizing: border-box;
        overflow: hidden;
        background: var(--dox-frame-ground);
        color: var(--dox-frame-text);
    }

    /* Every control states its own foreground. A control that inherited the
       user-agent button colour drew near-black text on the near-black shell. */
    .presentation-editor :is(button, input, select, textarea) {
        color: var(--dox-frame-text);
        background: color-mix(in srgb, var(--dox-frame-text) 8%, transparent);
        border: 1px solid var(--dox-frame-rule, currentColor);
        border-radius: 2px;
    }

    .presentation-editor :is(button, input, select, textarea):disabled {
        /* Still legible: a disabled control must read as unavailable, not as
           absent. */
        color: var(--dox-frame-text-muted);
        cursor: not-allowed;
    }

    .presentation-editor :is(button, input, select, textarea, a):focus-visible {
        outline: 2px solid var(--dox-frame-text);
        outline-offset: 1px;
    }

    .editor-chrome {
        display: flex;
        flex-wrap: wrap;
        gap: 0.75rem 1rem;
        align-items: baseline;
        justify-content: space-between;
    }

    .chrome-mark {
        margin: 0 0 0.2rem;
        color: var(--dox-frame-text-muted);
        font-family: var(--dox-font-mono);
        font-size: 0.68rem;
        letter-spacing: var(--dox-tracking-caps);
        text-transform: uppercase;
    }

    .chrome-title h2 {
        margin: 0;
        font-family: var(--dox-font-display);
        font-size: 1.35rem;
    }

    .chrome-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
        align-items: center;
    }

    .chrome-link, .presentation-editor button.chrome-action {
        display: inline-flex;
        align-items: center;
        min-height: 44px;
        padding: 0 0.75rem;
        color: var(--dox-frame-text);
        border: 1px solid var(--dox-frame-rule);
        border-radius: 2px;
        font-size: 0.8125rem;
    }

    .presentation-editor button.chrome-action {
        background: color-mix(in srgb, var(--dox-frame-text) 8%, transparent);
        cursor: pointer;
    }

    .chrome-identity {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        gap: 0 0.5rem;
        margin: 0;
        font-family: var(--font-mono, ui-monospace, monospace);
        font-size: 0.75rem;
    }

    .chrome-identity dd {
        margin: 0;
        overflow-wrap: anywhere;
    }

    .editor-failure { color: var(--dox-signal-alert, #ff9a8b); margin: 0; }
    .editor-failure code {
        font-family: var(--font-mono, ui-monospace, monospace);
        font-size: 0.8125rem;
        overflow-wrap: anywhere;
    }
    .editor-notice, .editor-state { margin: 0; color: var(--dox-frame-text-muted); }

    .presentation-empty, .migration-blockers {
        /* The shell owns the viewport; this panel takes the body row and
           scrolls inside it rather than growing the editor past it. */
        grid-row: 4;
        min-height: 0;
        max-width: 52rem;
        overflow: auto;
        padding: 1.25rem 1.5rem;
        border: 1px solid var(--dox-frame-rule);
        border-radius: 4px;
        background: color-mix(in srgb, var(--dox-frame-text) 3%, transparent);
    }

    .panel-mark {
        margin: 0 0 0.35rem;
        color: var(--dox-frame-text-muted);
        font-family: var(--dox-font-mono);
        font-size: 0.68rem;
        letter-spacing: var(--dox-tracking-caps);
        text-transform: uppercase;
    }

    .presentation-empty h3, .migration-blockers h3 {
        margin: 0 0 0.5rem;
        font-family: var(--dox-font-display);
        font-size: 1.2rem;
    }

    .presentation-empty p, .blockers-lead {
        margin: 0;
        max-width: 52ch;
        color: var(--dox-frame-text-muted);
        line-height: 1.55;
    }

    .blocker-subject { margin-top: 1.25rem; }

    .blocker-subject h4 {
        margin: 0 0 0.4rem;
        font-family: var(--dox-font-display);
        font-size: 0.95rem;
    }

    .blocker-subject ul {
        display: grid;
        gap: 0.5rem;
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .blocker {
        padding: 0.6rem 0.75rem;
        border: 1px solid var(--dox-frame-rule);
        border-radius: 2px;
    }

    .blocker-summary { margin: 0; max-width: 62ch; line-height: 1.5; }

    .blocker-detail {
        display: flex;
        flex-wrap: wrap;
        gap: 0 0.5rem;
        margin: 0.35rem 0 0;
        color: var(--dox-frame-text-muted);
        font-family: var(--font-mono, ui-monospace, monospace);
        font-size: 0.75rem;
        overflow-wrap: anywhere;
    }

    .region-switch { display: none; }

    .advanced > summary {
        min-height: 44px;
        padding: 0.6875rem 0;
        font-size: 0.8125rem;
        color: var(--dox-frame-text-muted);
        cursor: pointer;
    }

    .advanced > summary:focus-visible {
        outline: 2px solid var(--dox-frame-text);
        outline-offset: 1px;
    }

    .advanced .hint code { overflow-wrap: anywhere; }

    .editor-body {
        display: grid;
        grid-template-columns: minmax(12rem, 16rem) minmax(0, 1fr) minmax(18rem, 22rem);
        gap: 0.75rem;
        min-height: 0;
    }

    .outline, .stage, .inspector {
        min-height: 0;
        min-width: 0;
        overflow: auto;
    }

    .outline-add {
        display: grid;
        gap: 0.5rem;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid var(--dox-frame-rule, currentColor);
    }

    .outline ol {
        list-style: none;
        margin: 0.5rem 0 0;
        padding: 0;
        display: grid;
        gap: 0.5rem;
    }

    .outline-item {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 0.25rem;
        align-items: stretch;
        border: 1px solid var(--dox-frame-rule, currentColor);
    }

    .outline-item.is-selected { outline: 2px solid var(--dox-frame-text); }

    .presentation-editor .outline-select {
        display: grid;
        gap: 0.125rem;
        text-align: left;
        padding: 0.5rem;
        min-height: 44px;
        font: inherit;
        color: var(--dox-frame-text);
        background: none;
        border: 0;
        cursor: pointer;
    }

    .outline-index, .outline-id, .outline-summary {
        font-family: var(--font-mono, ui-monospace, monospace);
        font-size: 0.6875rem;
        color: var(--dox-frame-text-muted);
    }

    .outline-label { font-weight: 600; }

    .outline-move { display: grid; }

    .outline-move button, .role-switch button, .tablist button, .asset-actions button, .primary {
        min-width: 44px;
        min-height: 44px;
        font: inherit;
        cursor: pointer;
    }

    .badge {
        display: inline-block;
        padding: 0 0.375rem;
        border: 1px solid currentColor;
        font-size: 0.6875rem;
    }

    .badge.is-empty { color: var(--dox-frame-text-muted); }

    .toggle {
        display: flex;
        gap: 0.5rem;
        align-items: center;
        min-height: 44px;
        font-size: 0.8125rem;
        cursor: pointer;
    }

    .presentation-editor .toggle input {
        width: 1rem;
        height: 1rem;
        min-height: 0;
        accent-color: var(--dox-frame-text);
    }

    .edge-controls { display: grid; gap: 0.25rem; }

    .group-form {
        display: grid;
        gap: 0.5rem;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid var(--dox-frame-rule, currentColor);
    }

    .group-row {
        display: grid;
        gap: 0.25rem;
        padding: 0.5rem 0;
        border-bottom: 1px solid var(--dox-frame-rule, currentColor);
    }

    .group-name, .job-name { font-size: 0.875rem; }
    .group-meta, .job-meta { font-size: 0.75rem; color: var(--dox-frame-text-muted); }

    .generation-form {
        display: grid;
        gap: 0.5rem;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid var(--dox-frame-rule, currentColor);
    }

    .generation-form textarea { min-height: 6rem; }
    .generation-form select, .generation-form input { min-height: 44px; font: inherit; padding: 0 0.5rem; }

    .image-styles, .style-form { display: grid; gap: 0.5rem; min-width: 0; }
    .style-row { padding: 0.5rem 0; border-bottom: 1px solid var(--dox-frame-rule); }
    .style-row h4, .style-form h4 { margin: 0; font-size: 0.875rem; overflow-wrap: anywhere; }
    .style-text { white-space: pre-wrap; overflow-wrap: anywhere; }
    .style-form textarea { min-height: 6rem; }
    .style-choices { margin: 0; min-width: 0; border: 1px solid var(--dox-frame-rule); }
    .style-choices legend { font-size: 0.8125rem; }
    .style-choices .toggle span { overflow-wrap: anywhere; min-width: 0; }
    .style-choices .toggle input { flex-shrink: 0; }

    .job-row {
        display: grid;
        gap: 0.25rem;
        padding: 0.5rem 0;
        border-bottom: 1px solid var(--dox-frame-rule, currentColor);
    }

    .job-row button { min-height: 44px; font: inherit; cursor: pointer; }
    .job-error { font-family: var(--font-mono, ui-monospace, monospace); font-size: 0.6875rem; overflow-wrap: anywhere; }

    .panel-heading { margin: 0.5rem 0 0; font-size: 0.9375rem; }
    .group-actions { display: flex; flex-wrap: wrap; gap: 0.25rem; }
    .group-actions button { min-height: 44px; font: inherit; cursor: pointer; }

    .stage { display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 0.5rem; }

    .label-field { display: grid; gap: 0.25rem; font-size: 0.8125rem; }
    .label-field input { min-height: 44px; font: inherit; padding: 0 0.5rem; }

    .tablist { display: flex; flex-wrap: wrap; gap: 0.25rem; }

    .panel { display: grid; gap: 0.5rem; padding-top: 0.5rem; }

    .role-switch { display: flex; flex-wrap: wrap; gap: 0.25rem; }

    textarea {
        min-height: 14rem;
        font-family: var(--font-mono, ui-monospace, monospace);
        font-size: 0.8125rem;
        width: 100%;
        box-sizing: border-box;
    }

    .digests, .asset-grid, .panel ul { list-style: none; margin: 0; padding: 0; }

    .digests li, .panel li { font-size: 0.75rem; }

    .asset-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
        gap: 0.5rem;
    }

    .asset {
        border: 1px solid var(--dox-frame-rule, currentColor);
        padding: 0.5rem;
        display: grid;
        gap: 0.375rem;
    }

    .asset h3 { margin: 0; font-size: 0.9375rem; }
    .asset-alt { margin: 0; font-size: 0.75rem; color: var(--dox-frame-text-muted); }

    .asset dl, .edge dl, .panel dl {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        gap: 0 0.5rem;
        margin: 0;
        font-size: 0.75rem;
    }

    .asset dd, .edge dd, .panel dd { margin: 0; overflow-wrap: anywhere; }

    .asset-actions { display: flex; flex-wrap: wrap; gap: 0.25rem; }

    .edge { border-top: 1px solid var(--dox-frame-rule, currentColor); padding-top: 0.5rem; }
    .edge h3 { margin: 0 0 0.25rem; font-size: 0.875rem; text-transform: capitalize; }

    .agent-diff li {
        font-family: var(--font-mono, ui-monospace, monospace);
        overflow-wrap: anywhere;
    }

    .empty, .hint { color: var(--dox-frame-text-muted); font-size: 0.8125rem; margin: 0; }


    /* Raised controls and distinct panels make actions readable at a glance. */
    .presentation-editor button, .presentation-editor button.chrome-action, .chrome-link {
        min-height: 44px;
        padding: 0.55rem 0.8rem;
        font: inherit;
        font-size: 0.8125rem;
        font-weight: 600;
        cursor: pointer;
        border: 1px solid color-mix(in srgb, var(--dox-frame-text) 45%, var(--dox-frame-ground));
        border-radius: 6px;
        background: color-mix(in srgb, var(--dox-frame-text) 12%, var(--dox-frame-ground));
        text-decoration: none;
        box-shadow: 0 1px 2px #0003;
        box-sizing: border-box;
    }
    .presentation-editor button:not(:disabled):hover, .chrome-link:hover {
        background: color-mix(in srgb, var(--dox-frame-text) 22%, var(--dox-frame-ground));
        border-color: var(--dox-frame-text);
    }
    .presentation-editor button.primary,
    .presentation-editor button[aria-selected="true"],
    .presentation-editor button[aria-pressed="true"] {
        background: var(--dox-frame-text);
        color: var(--dox-frame-ground);
        border-color: var(--dox-frame-text);
    }
    .presentation-editor button.primary:not(:disabled):hover { background: #fff; }
    .presentation-editor button:disabled { opacity: 0.5; box-shadow: none; }
    .presentation-editor :is(input, select, textarea) { border-color: color-mix(in srgb, var(--dox-frame-text) 40%, var(--dox-frame-ground)); border-radius: 5px; }
    .region-heading { margin: 0 0 0.8rem; font-size: 0.95rem; }
    .workspace-details { flex-basis: 100%; font-size: 0.75rem; color: var(--dox-frame-text-muted); }
    .workspace-details summary { cursor: pointer; padding: 0.4rem 0; width: fit-content; }
    .workspace-details summary:focus-visible { outline: 2px solid currentColor; }
    .editor-chrome { align-items: center; padding-bottom: 0.75rem; border-bottom: 1px solid var(--dox-frame-rule); }
    .outline, .inspector {
        padding: 0.75rem;
        border: 1px solid color-mix(in srgb, var(--dox-frame-text) 30%, var(--dox-frame-ground));
        border-radius: 8px;
        background: var(--dox-frame-surface);
    }
    .stage { padding: 0.25rem; }
    .outline-item { border-radius: 6px; overflow: hidden; }
    .outline-item.is-selected { outline: none; border-color: var(--dox-frame-text); background: var(--dox-frame-surface-raised); box-shadow: inset 4px 0 var(--dox-frame-text); }
    .presentation-editor .outline-select { border: 0; background: transparent; box-shadow: none; text-align: left; }
    .outline-id { display: none; }
    .outline-move { gap: 0.25rem; padding: 0.25rem; }
    .tablist { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.4rem; padding-bottom: 0.8rem; border-bottom: 1px solid var(--dox-frame-rule); }
    .panel { gap: 0.8rem; padding-top: 0.8rem; }


    .stage { display: block; }
    .stage > .label-field { margin-bottom: 0.5rem; }
    .stage :global(.checkpoint-preview) { grid-template-rows: auto auto auto; }
    .stage :global(.realm) { max-height: none; }
    .steps-toggle { margin-bottom: 0.5rem; }
    .steps-collapsed .outline > :not(.steps-toggle) { display: none; }
    @media (min-width: 1024px) {
        .editor-body.steps-collapsed { grid-template-columns: 40px minmax(0, 1fr); }
    }
    .overview-gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 0.8rem; }
    .overview-gallery li { display: grid; align-content: start; gap: 0.4rem; min-width: 0; padding: 0.6rem; border: 1px solid var(--dox-frame-rule); border-radius: 6px; }
    .overview-gallery strong, .overview-gallery small { overflow-wrap: anywhere; }
    .overview-gallery img, .asset-preview { width: 100%; height: 160px; object-fit: contain; background: #fff; border-radius: 4px; }
    .presentation-editor .image-open { display: block; width: 100%; padding: 0; border: 0; background: transparent; box-shadow: none; cursor: zoom-in; }
    .presentation-editor .image-open:focus-visible { outline: 2px solid var(--dox-frame-text); outline-offset: 2px; }
    .source-catalogue { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.5rem; }
    .source-catalogue button { display: grid; gap: 0.35rem; text-align: left; }
    .source-catalogue code { font-size: 0.7rem; overflow-wrap: anywhere; }
    .presentation-editor { padding: 0.6rem; gap: 0.4rem; }
    .chrome-title h2 { font-size: 1.1rem; }
    .editor-body { grid-template-columns: 180px minmax(0, 1fr); grid-template-rows: max-content max-content; overflow: auto; align-items: start; }
    .outline { grid-row: 1 / span 2; position: sticky; top: 0; max-height: 100cqh; box-sizing: border-box; padding: 0.4rem; }
    .stage { display: block; min-height: auto; overflow: visible; grid-column: 2; grid-row: 1; }
    .inspector { grid-column: 2; grid-row: 2; overflow: visible; padding: 0.75rem; }
    .tablist { display: flex; flex-wrap: wrap; }
    .presentation-editor .outline-select { display: flex; align-items: center; gap: 0.5rem; width: 100%; padding: 0.3rem 0.4rem; }
    .outline-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 0.8rem; }
    .outline-index { flex-shrink: 0; min-width: 1.5em; }
    .outline-item { display: block; }
    .slide-run { margin-block: 0.25rem; }
    .presentation-editor .slide-toggle { display: flex; align-items: center; gap: 0.35rem; width: 100%; text-align: left; padding: 0.4rem; }
    .slide-toggle .outline-label { flex: 1; font-weight: 600; }
    .slide-count { font-size: 0.7rem; font-variant-numeric: tabular-nums; }
    .slide-run.is-active .slide-toggle { border-color: var(--dox-frame-text); }
    .outline .reveal-steps { padding-left: 0.65rem; }
    .outline ol[hidden], .steps-collapsed .outline-list { display: none; }
    .outline ol { gap: 0.2rem; }
    .outline-add { gap: 0.3rem; }
    .outline-add input { min-width: 0; width: 100%; box-sizing: border-box; }
    .add-hint { font-size: 0.7rem; margin-top: 0.4rem; }
    .inspector textarea { min-height: 24rem; padding: 0.8rem; font-size: 0.875rem; line-height: 1.65; tab-size: 2; resize: vertical; }
    @media (min-width: 1024px) {
        .editor-body { grid-row: 4; container-type: size; }
        .presentation-editor button, .presentation-editor button.chrome-action, .chrome-link { min-height: 32px; padding: 0.35rem 0.6rem; }
        .presentation-editor .outline-select { min-height: 32px; padding: 0.25rem 0.4rem; }
        .label-field input { min-height: 32px; }
        .stage { max-width: 100%; }
        .stage :global(.realm) { max-width: 760px; }
        .stage :global(.checkpoint-preview) { justify-items: stretch; }
    }

    @media (min-width: 1200px) {
        .authored-workspace .editor-body {
            grid-template-columns: 180px minmax(0, 1fr) minmax(0, 1fr);
            grid-template-rows: minmax(0, 1fr);
            overflow: hidden;
            align-items: stretch;
        }
        .authored-workspace .editor-body.steps-collapsed { grid-template-columns: 40px minmax(0, 1fr) minmax(0, 1fr); }
        .authored-workspace .outline { grid-row: 1; }
        .authored-workspace .stage { grid-column: 2; grid-row: 1; min-height: 0; overflow: auto; }
        .authored-workspace .inspector { grid-column: 3; grid-row: 1; min-height: 0; overflow: auto; }
    }

    @media (max-width: 1023px) {
        /* Stacked, the workspace is a document that scrolls, not three panes
           sharing one height. One region shows at a time so nothing paints
           over anything else, and the whole page — not a nested pane — is what
           scrolls. */
        .presentation-editor {
            grid-template-rows: auto auto auto auto;
            height: auto;
            min-height: 100%;
            overflow: visible;
        }

        .region-switch {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            position: sticky;
            top: 0;
            z-index: 2;
            background: var(--dox-frame-ground);
            border-bottom: 1px solid var(--dox-frame-rule);
        }

        .region-switch button {
            min-height: var(--touch-target-min, 44px);
            background: transparent;
            border: 0;
            border-bottom: 2px solid transparent;
            cursor: pointer;
            color: var(--dox-frame-text-muted);
        }

        .presentation-editor .region-switch button.active {
            color: var(--dox-frame-ground);
            background: var(--dox-frame-text);
            border-bottom-color: var(--dox-frame-text);
        }

        .editor-body {
            overflow: visible;
            grid-template-rows: auto;
            grid-template-columns: minmax(0, 1fr);
            grid-auto-rows: auto;
            min-height: auto;
        }

        .outline, .stage, .inspector { display: none; overflow: visible; min-height: auto; grid-column: auto; grid-row: auto; position: static; max-height: none; }
        .editor-body.show-steps .outline { display: block; }
        .editor-body.show-canvas .stage { display: grid; grid-template-rows: auto auto; }
        .editor-body.show-inspector .inspector { display: block; }
    }
</style>
