export interface AuthoredDocument {
    filename: string;
    url: string;
    renderUrl?: string;
    notesUrl: string | null;
    sha256: string;
}

export async function findAuthoredDocument(slug: string): Promise<AuthoredDocument | null> {
    const base = `/api/theses/${encodeURIComponent(slug)}/authored-document`;
    const response = await fetch(base, { cache: 'no-store' });
    if (response.status === 404) return null;
    if (!response.ok) {
        throw new Error('The selected authored document could not be opened. Check outputs/document/presentation.json and its files.');
    }
    const source = await response.json();
    if (typeof source.filename !== 'string' || source.url !== `${base}/html`
        || (source.notesUrl !== null && source.notesUrl !== `${base}/notes`)
        || typeof source.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(source.sha256)
        || (source.renderUrl !== undefined && source.renderUrl !== `${base}/render/${source.sha256}`)) {
        throw new Error('The server returned an invalid authored document selection.');
    }
    return { ...source, notesUrl: source.notesUrl ? `${source.notesUrl}?document_sha256=${source.sha256}` : null };
}
