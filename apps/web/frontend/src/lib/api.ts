const API_BASE = '/api';

export interface EvidenceRef {
    source: string;
    quote: string | null;
    url: string | null;
}

export interface DoxaNode {
    slug: string;
    title: string;
    belief: string | null;
    tags: string[];
    evidence: EvidenceRef[];
}

export interface Edge {
    source: string;
    target: string;
    type: string;
    alias?: string;  // Human-readable label for this relationship
}

export interface Graph {
    nodes: DoxaNode[];
    edges: Edge[];
    version: string;
}

export interface DoxaDetail extends DoxaNode {
    content: string;
    incoming: Edge[];
    outgoing: Edge[];
    diegeses: string[];
}

export interface DiegesisSection {
    title: string;
    doxai: string[];
}

/**
 * Which rendering model a thesis's presentation plays through.
 *
 * `document` is one authored HTML file driven through the MessagePort bridge;
 * `slides` is the legacy per-slide tree. They are different products, so a
 * caller reads this rather than inferring a model from `slide_count`, which a
 * document does not have.
 */
export type PresentationModel = 'document' | 'slides' | 'none';

export interface ThesisRef {
    slug: string;
    walk: string;
    has_presentation: boolean;
    presentation_model: PresentationModel;
}

export interface DiegesisListItem {
    slug: string;
    title: string;
    subtitle: string | null;
    section_count: number;
    walk_count: number;
    walks: string[];  // Walk names only
}

export interface DiegesisDetail {
    slug: string;
    title: string;
    subtitle: string | null;
    sections: Record<string, DiegesisSection>;  // section_key -> {title, doxai[]}
    walks: Record<string, string[]>;  // walk_name -> [section_keys]
    theses: ThesisRef[];
    body: string;
}

export async function fetchGraph(): Promise<Graph> {
    const res = await fetch(`${API_BASE}/graph`);
    return res.json();
}

export async function fetchScopedGraph(
    params: { diegesis?: string; walk?: string; root?: string; hops?: number }
): Promise<Graph> {
    const url = new URL(`${API_BASE}/graph/scoped`, window.location.href);
    if (params.diegesis) url.searchParams.set('diegesis', params.diegesis);
    if (params.walk) url.searchParams.set('walk', params.walk);
    if (params.root) url.searchParams.set('root', params.root);
    if (params.hops) url.searchParams.set('hops', String(params.hops));
    const res = await fetch(url);
    return res.json();
}

export async function fetchVersion(): Promise<string> {
    const res = await fetch(`${API_BASE}/graph/version`);
    const data = await res.json();
    return data.version;
}

export async function fetchDoxa(slug: string): Promise<DoxaDetail> {
    const res = await fetch(`${API_BASE}/doxai/${slug}`);
    if (!res.ok) throw new Error(`Failed to load details (${res.status})`);
    return res.json();
}

export interface DoxaLabel {
    slug: string;
    short: string | null;
    belief: string | null;
}

export async function fetchDoxaLabel(slug: string): Promise<DoxaLabel> {
    const res = await fetch(`${API_BASE}/doxai/${slug}/label`);
    if (!res.ok) throw new Error(`Failed to load label (${res.status})`);
    return res.json();
}

export async function fetchDoxaContent(slug: string): Promise<string> {
    const res = await fetch(`${API_BASE}/doxai/${slug}/content`);
    return res.text();
}

export async function fetchDiegeses(): Promise<DiegesisListItem[]> {
    const res = await fetch(`${API_BASE}/diegeses`);
    return res.json();
}

export async function fetchDiegesis(slug: string): Promise<DiegesisDetail> {
    const res = await fetch(`${API_BASE}/diegeses/${slug}`);
    return res.json();
}

// ============ Pipeline Types ============

export type PhantasiaStatus = 'unprocessed' | 'processing' | 'processed' | 'archived' | 'abandoned' | 'failed';
export type EvidenceStatus = 'provisional' | 'validated' | 'retracted' | 'superseded';
export type EvidenceType = 'empirical' | 'theoretical' | 'anecdotal' | 'expert-opinion' | 'logical';
export type EvidenceStrength = 'strong' | 'moderate' | 'weak';
export type EdgeType = 'supports' | 'contradicts' | 'requires' | 'elaborates' | 'grounds' | 'causes' | 'resolves';
export type EdgeConfidence = 'high' | 'medium' | 'low';

export interface PipelineStats {
    inbox_count: number;
    phantasiai: Record<string, number>;
    doxai_count: number;
    evidence_count: number;
    edges_count: number;
    diegeses_count: number;
}

export interface PhantasiaListItem {
    slug: string;
    title: string;
    source: string;
    status: PhantasiaStatus;
    encountered: string;
    doxai_count: number;
    evidence_count: number;
}

export interface DoxaRef {
    slug: string;
    belief: string | null;
}

export interface EvidenceRefSummary {
    slug: string;
    assertion: string | null;
}

export interface PhantasiaDetail {
    slug: string;
    title: string;
    source: string;
    status: PhantasiaStatus;
    encountered: string;
    channel: string | null;
    shared_by: string | null;
    tags: string[];
    extracted_doxai: DoxaRef[];
    extracted_evidence: EvidenceRefSummary[];
    content: string;
}

export interface EvidenceListItem {
    slug: string;
    assertion: string;
    source: string;
    type: EvidenceType;
    strength: EvidenceStrength;
    status: EvidenceStatus;
}

export interface EvidenceDetail extends EvidenceListItem {
    source_url: string | null;
    provenance: { phantasia?: string; extracted?: string } | null;
    annotations: string[];
    gaps: string[];
    content: string;
}

export interface EdgeListItem {
    source: string;
    target: string;
    type: EdgeType;
    alias: string | null;  // Human-readable label for this relationship
    strength: EvidenceStrength;
    confidence: EdgeConfidence;
    disputed: boolean;
}

export interface EdgeDetail extends EdgeListItem {
    rationale: string | null;
    annotation: string | null;  // Legacy field
    reviewer_notes: string | null;
    provenance: { method: string; phantasia?: string; pass_date?: string } | null;
    created: string | null;
}

export interface InboxItem {
    filename: string;
    size_bytes: number;
    modified: string;
    ingested: boolean;
}

// ============ Pipeline API Functions ============

export async function fetchPipelineStats(): Promise<PipelineStats> {
    const res = await fetch(`${API_BASE}/pipeline/stats`);
    return res.json();
}

export async function fetchPhantasiai(status?: PhantasiaStatus): Promise<PhantasiaListItem[]> {
    const url = new URL(`${API_BASE}/phantasiai`, window.location.href);
    if (status) url.searchParams.set('status', status);
    const res = await fetch(url);
    return res.json();
}

export async function fetchPhantasia(slug: string): Promise<PhantasiaDetail> {
    const res = await fetch(`${API_BASE}/phantasiai/${slug}`);
    return res.json();
}

export async function createPhantasia(data: {
    source: string;
    title?: string;
    channel?: string;
    shared_by?: string;
    tags?: string[];
    content?: string;
}): Promise<{ slug: string; status: string }> {
    const res = await fetch(`${API_BASE}/phantasiai`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    return res.json();
}

export async function updatePhantasia(slug: string, data: {
    status?: PhantasiaStatus;
    tags?: string[];
    content?: string;
}): Promise<{ slug: string; status: string }> {
    const res = await fetch(`${API_BASE}/phantasiai/${slug}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    return res.json();
}

export async function archivePhantasia(slug: string): Promise<{ slug: string; status: string }> {
    const res = await fetch(`${API_BASE}/phantasiai/${slug}`, { method: 'DELETE' });
    return res.json();
}

export interface ExtractionResult {
    slug: string;
    status: string;
    created_doxai: string[];
    created_evidence: string[];
    created_edges: number;
    skipped_duplicates: number;
    suggested_links: number;
}

export async function extractPhantasia(slug: string, focus?: string): Promise<ExtractionResult> {
    const url = new URL(`${API_BASE}/phantasiai/${slug}/extract`, window.location.href);
    if (focus) url.searchParams.set('focus', focus);
    const res = await fetch(url, { method: 'POST' });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Extraction failed');
    }
    return res.json();
}

// ============ Evidence API Functions ============

export async function fetchEvidence(params?: {
    type?: EvidenceType;
    strength?: EvidenceStrength;
    status?: EvidenceStatus;
}): Promise<EvidenceListItem[]> {
    const url = new URL(`${API_BASE}/evidence`, window.location.href);
    if (params?.type) url.searchParams.set('type', params.type);
    if (params?.strength) url.searchParams.set('strength', params.strength);
    if (params?.status) url.searchParams.set('status', params.status);
    const res = await fetch(url);
    return res.json();
}

export async function fetchEvidenceDetail(slug: string): Promise<EvidenceDetail> {
    const res = await fetch(`${API_BASE}/evidence/${slug}`);
    return res.json();
}

export async function createEvidence(data: {
    assertion: string;
    source: string;
    source_url?: string;
    type?: EvidenceType;
    strength?: EvidenceStrength;
    status?: EvidenceStatus;
    from_phantasia?: string;
    annotations?: string[];
    gaps?: string[];
    content?: string;
}): Promise<{ slug: string; status: string }> {
    const res = await fetch(`${API_BASE}/evidence`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    return res.json();
}

export async function updateEvidence(slug: string, data: {
    assertion?: string;
    source?: string;
    source_url?: string;
    type?: EvidenceType;
    strength?: EvidenceStrength;
    status?: EvidenceStatus;
    annotations?: string[];
    gaps?: string[];
    content?: string;
}): Promise<{ slug: string; status: string }> {
    const res = await fetch(`${API_BASE}/evidence/${slug}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    return res.json();
}

export async function deleteEvidence(slug: string): Promise<{ slug: string; status: string }> {
    const res = await fetch(`${API_BASE}/evidence/${slug}`, { method: 'DELETE' });
    return res.json();
}

// ============ Edge API Functions ============

export async function fetchEdges(params?: {
    source?: string;
    target?: string;
    type?: EdgeType;
}): Promise<EdgeListItem[]> {
    const url = new URL(`${API_BASE}/edges`, window.location.href);
    if (params?.source) url.searchParams.set('source', params.source);
    if (params?.target) url.searchParams.set('target', params.target);
    if (params?.type) url.searchParams.set('type', params.type);
    const res = await fetch(url);
    return res.json();
}

export async function fetchEdgeDetail(source: string, target: string): Promise<EdgeDetail> {
    const res = await fetch(`${API_BASE}/edges/${source}/${target}`);
    return res.json();
}

export async function createEdge(data: {
    source: string;
    target: string;
    type: EdgeType;
    alias?: string;
    strength?: EvidenceStrength;
    annotation?: string;
    from_phantasia?: string;
}): Promise<{ source: string; target: string; status: string }> {
    const res = await fetch(`${API_BASE}/edges`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    return res.json();
}

export async function updateEdge(source: string, target: string, data: {
    type?: EdgeType;
    alias?: string;
    strength?: EvidenceStrength;
    confidence?: EdgeConfidence;
    rationale?: string;
    annotation?: string;
    disputed?: boolean;
    reviewer_notes?: string;
}): Promise<{ source: string; target: string; status: string }> {
    const res = await fetch(`${API_BASE}/edges/${source}/${target}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    return res.json();
}

export async function deleteEdge(source: string, target: string): Promise<{ source: string; target: string; status: string }> {
    const res = await fetch(`${API_BASE}/edges/${source}/${target}`, { method: 'DELETE' });
    return res.json();
}

export async function fetchInbox(): Promise<InboxItem[]> {
    const res = await fetch(`${API_BASE}/inbox`);
    return res.json();
}

export async function uploadToInbox(file: File): Promise<{ filename: string; size_bytes: number; status: string }> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/inbox`, {
        method: 'POST',
        body: formData,
    });
    return res.json();
}

export async function deleteFromInbox(filename: string): Promise<{ filename: string; status: string }> {
    const res = await fetch(`${API_BASE}/inbox/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    return res.json();
}

// ============ Thesis/Presentation Types ============

export interface ThesisListItem {
    slug: string;
    name: string;
    diegesis: string;
    walk: string;
    /** The legacy slide tree only; a document model always reports zero. */
    slide_count: number;
    slides_with_images: number;
    has_presentation: boolean;
    presentation_model: PresentationModel;
    has_essay: boolean;
}

export interface SlideUsage {
    thesis_slug: string;
    thesis_title: string;
    slide_slug: string;
    slide_number: number;
    slide_title: string;
}

export interface ThesisDetail {
    slug: string;
    name: string;
    title: string;
    subtitle: string | null;
    diegesis: string;
    walk: string;
    audience: string | null;
    description: string | null;
    slide_count: number;
    slides_with_images: number;
}

/**
 * One legacy slide, reduced to what a reader may still ask the window for.
 *
 * This is the read-only compatibility window over trees that have not been
 * migrated. The legacy producer still sends its bundles, selection flags, and
 * layout mode on the wire; this client declares none of them, because a
 * declared member is a member some future call site will reach for, and no
 * display decision in this product may derive from one. In the Step workspace
 * every media item is an equal first-class asset and the only navigation
 * authority is `checkpoint_order`.
 */
export interface SlideDetail {
    number: number;
    slug: string;
    title: string;
    body: string;
    speaker_notes: string;
    doxai: string[];
}

// ============ Thesis/Presentation API Functions ============

export async function fetchTheses(params?: {
    diegesis?: string;
    walk?: string;
}): Promise<ThesisListItem[]> {
    const url = new URL(`${API_BASE}/theses`, window.location.href);
    if (params?.diegesis) url.searchParams.set('diegesis', params.diegesis);
    if (params?.walk) url.searchParams.set('walk', params.walk);
    const res = await fetch(url);
    return res.json();
}

export async function fetchSlideUsages(doxaSlug: string): Promise<SlideUsage[]> {
    const url = new URL(`${API_BASE}/theses/slide-usages`, window.location.href);
    url.searchParams.set('doxa', doxaSlug);
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed to fetch slide usages: ${res.statusText}`);
    return res.json();
}

export async function fetchThesis(slug: string): Promise<ThesisDetail> {
    const res = await fetch(`${API_BASE}/theses/${slug}`);
    if (!res.ok) {
        throw new Error(`Failed to fetch thesis: ${res.statusText}`);
    }
    return res.json();
}

export async function fetchSlide(thesisSlug: string, slideSlug: string): Promise<SlideDetail> {
    const res = await fetch(`${API_BASE}/theses/${thesisSlug}/slides/${slideSlug}`);
    if (!res.ok) {
        throw new Error(`Failed to fetch slide: ${res.statusText}`);
    }
    return res.json();
}

/**
 * Build the full URL for a thesis asset (slide image).
 * @param thesisSlug - The thesis slug
 * @param slidePath - Path within the slide, e.g., "01-search/images/main/outputs/generated.png"
 */
export function getThesisAssetUrl(thesisSlug: string, slidePath: string): string {
    return `${API_BASE}/thesis-assets/${thesisSlug}/outputs/presentation/slides/${slidePath}`;
}

// Every primary/selected/display/layout decision is gone from this client.
//
// `setPrimaryImage` and `findDisplayImage` were the only reachable ways the
// product marked one bundle as the one to show and fell back to `images[0]`;
// `updateSlideLayout` was the only way it wrote a slide's layout mode. The Step
// workspace holds no such decision: every media item is an equal first-class
// asset a Step either declares or does not, and a step's position is its index
// in `checkpoint_order`. A client helper that resolved a "display" bundle or
// wrote a layout mode would reintroduce an authority no producer in the target
// system has, so none is declared here — not even as a type. What remains is
// the read-only compatibility window over trees that have not been migrated;
// `tests/test_presentations_legacy_boundary.py` holds this surface to it.

// ============ Image Generation Types ============

export type ImageResolution = '1k' | '2k' | '4k';

export interface GenerateImageOptions {
    resolution?: ImageResolution;
    aspect_ratio?: string;
    versions?: number;
}

export interface GenerateImageResult {
    success: boolean;
    job_id: string;
    message: string;
}

export interface GenerateImageStatus {
    status: 'pending' | 'running' | 'complete' | 'error';
    message: string | null;
    images_generated: number;
}

export async function generateImage(
    thesisSlug: string,
    slideSlug: string,
    imageId: string,
    options?: GenerateImageOptions
): Promise<GenerateImageResult> {
    const res = await fetch(
        `${API_BASE}/theses/${thesisSlug}/slides/${slideSlug}/images/${imageId}/generate`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(options || {}),
        }
    );
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to start image generation');
    }
    return res.json();
}

export async function getGenerateStatus(
    thesisSlug: string,
    jobId: string
): Promise<GenerateImageStatus> {
    const res = await fetch(`${API_BASE}/theses/${thesisSlug}/generate/status/${jobId}`);
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to get generation status');
    }
    return res.json();
}

// ============ Batch Generation Types ============

export interface BatchGenerateOptions {
    slide_slugs: string[];
    image_id?: string;
    resolution?: ImageResolution;
    aspect_ratio?: string;
    versions?: number;
}

export interface BatchGenerateResult {
    success: boolean;
    job_id: string;
    message: string;
    started: number;
    skipped: number;
}

export interface BatchGenerateStatus {
    status: 'pending' | 'running' | 'complete' | 'error';
    message: string | null;
    total: number;
    completed: number;
    failed: number;
    current_slide: string | null;
}

export async function batchGenerate(
    thesisSlug: string,
    options: BatchGenerateOptions
): Promise<BatchGenerateResult> {
    const res = await fetch(
        `${API_BASE}/theses/${thesisSlug}/generate/batch`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(options),
        }
    );
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to start batch generation');
    }
    return res.json();
}

export async function getBatchGenerateStatus(
    thesisSlug: string,
    jobId: string
): Promise<BatchGenerateStatus> {
    const res = await fetch(`${API_BASE}/theses/${thesisSlug}/generate/batch/status/${jobId}`);
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to get batch generation status');
    }
    return res.json();
}

// Legacy slide, image-bundle, and stylesheet *authorship* is not part of this
// client any more.
//
// Authoring a step's source, its media, and its styles is the Step workspace's
// job, and it does that through `$lib/presentation/deck` against the revisioned
// vault presentation. The legacy routes for slide text, slide HTML, slide
// layout, image bundles, image definitions, and thesis stylesheets are refused
// by the server once a deck has been migrated (`PRES_LEGACY_READ_ONLY`), so a
// client function that called one would be a control whose only possible answer
// is a refusal.

// ============ Annotation Types & Functions ============

export interface Annotation {
    id: string;
    slide_slug: string;
    content: string;
    created_at: string;
}

export async function fetchAnnotations(thesisSlug: string): Promise<Annotation[]> {
    const res = await fetch(`${API_BASE}/theses/${thesisSlug}/annotations`);
    if (!res.ok) {
        throw new Error('Failed to fetch annotations');
    }
    return res.json();
}

export async function createAnnotation(
    thesisSlug: string,
    slideSlug: string,
    content: string
): Promise<Annotation> {
    const res = await fetch(
        `${API_BASE}/theses/${thesisSlug}/slides/${slideSlug}/annotations`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        }
    );
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to create annotation');
    }
    const data = await res.json();
    return data.annotation;
}

export async function deleteAnnotation(
    thesisSlug: string,
    annotationId: string
): Promise<void> {
    const res = await fetch(
        `${API_BASE}/theses/${thesisSlug}/annotations/${annotationId}`,
        { method: 'DELETE' }
    );
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to delete annotation');
    }
}

// ============ Submission Types & Functions ============

export type SubmissionStatus = 'idle' | 'processing' | 'complete' | 'error';

export interface SubmissionStatusResponse {
    status: SubmissionStatus;
    message: string | null;
    job_id: string | null;
}

export async function submitAnnotations(thesisSlug: string): Promise<SubmissionStatusResponse> {
    const res = await fetch(
        `${API_BASE}/theses/${thesisSlug}/annotations/submit`,
        { method: 'POST' }
    );
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to submit annotations');
    }
    return res.json();
}

export async function getSubmissionStatus(
    thesisSlug: string,
    jobId: string
): Promise<SubmissionStatusResponse> {
    const res = await fetch(`${API_BASE}/theses/${thesisSlug}/annotations/status/${jobId}`);
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to get submission status');
    }
    return res.json();
}

// ============ Build Types & Functions ============

export type BuildStatus = 'pending' | 'running' | 'complete' | 'error';

export interface BuildOptions {
    verbose?: boolean;
    skip_pptx?: boolean;
    skip_speaker_notes?: boolean;
    skip_images?: boolean;
    include_style_ref?: boolean;
}

export interface BuildResult {
    success: boolean;
    job_id: string;
    message: string;
}

export interface BuildStatusResponse {
    status: BuildStatus;
    message: string | null;
    build_dir: string | null;
    files: string[];
}

export async function buildPresentation(
    thesisSlug: string,
    options?: BuildOptions
): Promise<BuildResult> {
    const res = await fetch(
        `${API_BASE}/theses/${thesisSlug}/build`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(options || {}),
        }
    );
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to start build');
    }
    return res.json();
}

export async function getBuildStatus(
    thesisSlug: string,
    jobId: string
): Promise<BuildStatusResponse> {
    const res = await fetch(`${API_BASE}/theses/${thesisSlug}/build/status/${jobId}`);
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to get build status');
    }
    return res.json();
}

// ============ Dev Tasks Types & Functions ============

export type DevTaskStatus =
    | 'pending'
    | 'processing'
    | 'testing'
    | 'awaiting_approval'
    | 'merged'
    | 'rejected'
    | 'error'
    | 'failed';

export interface DevTasksPreflightResponse {
    uncommitted_changes: number;
    warning: string | null;
    safe_to_proceed: boolean;
}

export interface DevTasksSubmitResponse {
    status: DevTaskStatus;
    message: string;
    job_id: string | null;
    worktree: string | null;
    branch: string | null;
}

export interface DevTasksStatusResponse {
    status: DevTaskStatus;
    job_id: string;
    worktree: string | null;
    branch: string | null;
    message: string | null;
    test_results: {
        passed: boolean;
        output: string;
    } | null;
    diff_stats: {
        files_changed: number;
        insertions: number;
        deletions: number;
    } | null;
}

export interface DevTasksDiffResponse {
    diff: string;
    files: string[];
}

export interface DevTasksMergeResponse {
    status: 'merged';
    commit: string;
    message: string;
}

export interface DevTasksRejectResponse {
    status: 'rejected';
    cleaned_up: boolean;
}

export async function preflightDevTasks(): Promise<DevTasksPreflightResponse> {
    const res = await fetch(`${API_BASE}/dev-tasks/preflight`);
    if (!res.ok) {
        throw new Error('Preflight check failed');
    }
    return res.json();
}

export async function submitDevTasks(tasks: string[]): Promise<DevTasksSubmitResponse> {
    const res = await fetch(`${API_BASE}/dev-tasks/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tasks }),
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to submit dev tasks');
    }
    return res.json();
}

export async function getDevTaskStatus(jobId: string): Promise<DevTasksStatusResponse> {
    const res = await fetch(`${API_BASE}/dev-tasks/status/${jobId}`);
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to get job status');
    }
    return res.json();
}

export async function getDevTaskDiff(jobId: string): Promise<DevTasksDiffResponse> {
    const res = await fetch(`${API_BASE}/dev-tasks/${jobId}/diff`);
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to get diff');
    }
    return res.json();
}

export async function mergeDevTask(jobId: string): Promise<DevTasksMergeResponse> {
    const res = await fetch(`${API_BASE}/dev-tasks/${jobId}/merge`, {
        method: 'POST',
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to merge');
    }
    return res.json();
}

export async function rejectDevTask(jobId: string): Promise<DevTasksRejectResponse> {
    const res = await fetch(`${API_BASE}/dev-tasks/${jobId}/reject`, {
        method: 'POST',
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to reject');
    }
    return res.json();
}
