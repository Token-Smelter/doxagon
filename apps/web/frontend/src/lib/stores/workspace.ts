import { browser } from '$app/environment';
import { get, writable } from 'svelte/store';

export type Ground = 'cream' | 'nigredo';
export type Workspace = 'graph' | 'presentations';

export interface WorkspaceNavigationItem {
    id: Workspace;
    label: string;
    href: string;
    available: boolean;
}

export const workspaceNavigation: WorkspaceNavigationItem[] = [
    { id: 'graph', label: 'Knowledge Graph', href: '/', available: true },
    { id: 'presentations', label: 'Presentations', href: '/presentations', available: true },
];

export function workspaceForPath(pathname: string): Workspace {
    return pathname.startsWith('/presentations') ? 'presentations' : 'graph';
}

const groundPreferenceKey = 'doxagon-ground';

export const groundPreference = writable<Ground>('cream');

function applyGround(ground: Ground) {
    document.body.classList.toggle('dox-invert', ground === 'nigredo');
}

export function initializeGroundPreference() {
    if (!browser) return;

    const stored = window.localStorage.getItem(groundPreferenceKey);
    const ground: Ground = stored === 'nigredo' ? 'nigredo' : 'cream';
    applyGround(ground);
    groundPreference.set(ground);
}

export function setGroundPreference(ground: Ground) {
    if (!browser) return;

    applyGround(ground);
    window.localStorage.setItem(groundPreferenceKey, ground);
    groundPreference.set(ground);
}

export function toggleGroundPreference() {
    setGroundPreference(get(groundPreference) === 'cream' ? 'nigredo' : 'cream');
}
