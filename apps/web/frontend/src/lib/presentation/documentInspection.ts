import type { AuthoredDocument } from './authoredDocument';

export interface InspectionItem {
    id: string; kind: string; label: string; status: string; path?: string;
    sha256?: string; bytes?: number; width?: number; height?: number;
    alt?: string; media_type?: string; usages?: string[]; provenance?: string; original?: string;
    dependencies?: string[]; references?: string[];
}
export interface DocumentInspection {
    schema: string; snapshot: string; model: 'authored'; project: string; title: string; audience: string;
    document: InspectionItem; notes: InspectionItem | null; items: InspectionItem[];
    notes_metadata: { documentId: string; edition: string; cues: string[] } | null;
    cues: { id: string; title: string; section?: string; line: number }[];
    sections: { id: string; title: string; line: number }[];
    usages: { id: string; stable: boolean; alt: string; section: string | null; line: number; image: string | null }[];
    links: Record<string, string>; checks: { code: string; message: string }[]; coverage: string;
    authoring?: { status: string; validation: string; assets: RegisteredAsset[]; styles: RegisteredAsset[] };
}
export interface RegisteredAsset {
    key: string; label: string; dialect: string; definition: string | null; references: string[]; usages: string[];
    variants: { id: string; image: string | null; status: string; provenance: string; current_definition: string;
        receipt?: string; generated_with?: { provider: string; model: string }; changed_inputs?: string[] }[];
}
export interface GenerationComponent {
    key: string; role: string; tags: string[]; requires: string[];
    definition: string | null; body: string | null; references: string[]; status: string;
}
export interface GenerationOrigin {
    label: string; definition: string | null; image_prompt: string | null; constraints: string | null;
    image_tags: string[]; components: GenerationComponent[]; references: string[]; unresolved_tags: string[];
    current_assembled: string | null; current_settings: Record<string, unknown> | null;
    saved_prompts: { item: string; status: string }[]; saved_config?: string;
    receipt: string | null; provider: Record<string, string> | null; saved_settings: Record<string, unknown> | null;
    current_definition: string; recorded_references: { item: string; sha256: string; status: string }[]; issues: string[];
}
export interface ImageGeneration { origins: GenerationOrigin[]; message: string; association?: string }
export interface InspectionPage { item: InspectionItem; text?: string; offset?: number; next?: number | null; total?: number; generation?: ImageGeneration }
export const inspectionBase = (slug: string) => `/api/theses/${encodeURIComponent(slug)}/document-workspace`;
export async function inspectionRequest<T>(url: string): Promise<T> {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail?.message ?? 'The inspection could not be loaded. Refresh to try the current revision.');
    }
    return response.json();
}
export const readInspection = (slug: string) => inspectionRequest<DocumentInspection>(inspectionBase(slug));
export const itemUrl = (view: DocumentInspection, id: string) =>
    `${inspectionBase(view.project)}/items/${encodeURIComponent(id)}?snapshot=${view.snapshot}`;
export const imageUrl = (view: DocumentInspection, id: string, thumbnail = false) =>
    `${inspectionBase(view.project)}/items/${encodeURIComponent(id)}/image?snapshot=${view.snapshot}&thumbnail=${thumbnail}`;
export const inspectedSource = (view: DocumentInspection, source: AuthoredDocument): AuthoredDocument => ({
    ...source,
    notesUrl: view.notes?.status === 'current'
        ? `${inspectionBase(view.project)}/items/${view.notes.id}/notes?snapshot=${view.snapshot}` : null,
});
