// Domain remains encoded by tag text and mark geometry; graph ink is renderer-neutral.
export const DOMAIN_COLORS: Record<string, string> = {};

export function getDomainColor(_tags: string[]): string {
    return 'var(--dox-text-primary)';
}
