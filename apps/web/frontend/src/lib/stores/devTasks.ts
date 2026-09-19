import { writable, derived } from 'svelte/store';

export interface DevTask {
    id: string;
    content: string;
    created_at: string;
}

// Pending dev tasks (not yet submitted)
export const devTasks = writable<DevTask[]>([]);

// Modal state
export const devTasksModalOpen = writable(false);

// Submission state
export const devTasksSubmitting = writable(false);
export const devTasksError = writable<string | null>(null);

// Derived count
export const devTaskCount = derived(devTasks, $tasks => $tasks.length);

// Add a new task
export function addDevTask(content: string): void {
    const task: DevTask = {
        id: crypto.randomUUID().slice(0, 8),
        content: content.trim(),
        created_at: new Date().toISOString(),
    };
    devTasks.update(tasks => [...tasks, task]);
}

// Remove a task
export function removeDevTask(id: string): void {
    devTasks.update(tasks => tasks.filter(t => t.id !== id));
}

// Clear all tasks
export function clearDevTasks(): void {
    devTasks.set([]);
}

// Open/close modal
export function openDevTasksModal(): void {
    devTasksModalOpen.set(true);
}

export function closeDevTasksModal(): void {
    devTasksModalOpen.set(false);
}
