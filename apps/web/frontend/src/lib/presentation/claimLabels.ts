const MAX_LABEL = 32;

/**
 * The chip text for a doxa.
 *
 * An author's `short:` field wins because it is written for this size. Without
 * one the belief is cut at the last word boundary inside 32 characters, so a
 * chip never breaks a word and never carries a sentence. A first word longer
 * than that budget is kept whole and the chip grows, because half a word reads
 * as a different word.
 */
export function claimLabel(slug: string, short: string | null, belief: string | null): string {
    const authored = short?.trim();
    if (authored) return authored;
    const text = belief?.trim();
    if (!text) return slug;
    if (text.length <= MAX_LABEL) return text;
    const boundary = text.slice(0, MAX_LABEL).lastIndexOf(' ');
    if (boundary > 0) return `${text.slice(0, boundary).trimEnd()}…`;
    const firstWordEnd = text.indexOf(' ');
    return firstWordEnd === -1 ? text : `${text.slice(0, firstWordEnd)}…`;
}

/** The view this platform already has for a doxa: the graph with it selected. */
export function claimHref(slug: string): string {
    return `/?node=${encodeURIComponent(slug)}`;
}
