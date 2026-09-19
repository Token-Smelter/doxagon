import { readable } from 'svelte/store';
import { browser } from '$app/environment';

export interface MediaState {
    mobile: boolean;
    compact: boolean;
    shell: 'compact' | 'mobile' | 'tablet' | 'desktop' | 'wide';
}

export const media = readable<MediaState>(
    { mobile: false, compact: false, shell: 'desktop' },
    (set) => {
        if (!browser) return;
        const mobileQuery = window.matchMedia('(max-width: 768px)');
        const compactQuery = window.matchMedia('(max-width: 480px)');
        const tabletQuery = window.matchMedia('(max-width: 1024px)');
        const wideQuery = window.matchMedia('(min-width: 1440px)');
        const update = () => set({
            mobile: mobileQuery.matches,
            compact: compactQuery.matches,
            shell: compactQuery.matches
                ? 'compact'
                : mobileQuery.matches
                    ? 'mobile'
                    : tabletQuery.matches
                        ? 'tablet'
                        : wideQuery.matches
                            ? 'wide'
                            : 'desktop',
        });
        const queries = [mobileQuery, compactQuery, tabletQuery, wideQuery];
        queries.forEach((query) => query.addEventListener('change', update));
        update();
        return () => queries.forEach((query) => query.removeEventListener('change', update));
    }
);
