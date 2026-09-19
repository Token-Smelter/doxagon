import { writable } from 'svelte/store';
import { browser } from '$app/environment';

// Text size steps: small (0.8rem), medium (1rem), large (1.2rem), x-large (1.4rem)
const SIZES = [0.8, 1.0, 1.2, 1.4];
const DEFAULT_INDEX = 1; // medium
const STORAGE_KEY = 'doxagon-text-size';

function createTextSizeStore() {
    // Load from localStorage or use default
    const storedIndex = browser
        ? parseInt(localStorage.getItem(STORAGE_KEY) || String(DEFAULT_INDEX))
        : DEFAULT_INDEX;
    const initialIndex = Math.min(Math.max(storedIndex, 0), SIZES.length - 1);

    const { subscribe, update, set } = writable(initialIndex);

    return {
        subscribe,
        increase: () => update(n => {
            const newIndex = Math.min(n + 1, SIZES.length - 1);
            if (browser) localStorage.setItem(STORAGE_KEY, String(newIndex));
            return newIndex;
        }),
        decrease: () => update(n => {
            const newIndex = Math.max(n - 1, 0);
            if (browser) localStorage.setItem(STORAGE_KEY, String(newIndex));
            return newIndex;
        }),
        reset: () => {
            if (browser) localStorage.setItem(STORAGE_KEY, String(DEFAULT_INDEX));
            set(DEFAULT_INDEX);
        },
        getSize: (index: number) => SIZES[index] + 'rem',
        getSizes: () => SIZES,
        canIncrease: (index: number) => index < SIZES.length - 1,
        canDecrease: (index: number) => index > 0
    };
}

export const textSizeIndex = createTextSizeStore();
