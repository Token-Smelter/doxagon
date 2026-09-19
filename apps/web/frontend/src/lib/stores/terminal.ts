/**
 * Terminal store for streaming job output.
 *
 * Supports multiple concurrent jobs with tabbed interface.
 * Each job has its own EventSource connection and output buffer.
 */

import { writable, derived, get } from 'svelte/store';

// Terminal visibility and position
export const terminalOpen = writable(false);
export const terminalMinimized = writable(false);
export const terminalPosition = writable({ x: 100, y: 100 });
export const terminalSize = writable({ width: 600, height: 300 });

// Job types
export type JobStatus = 'running' | 'complete' | 'error';

export interface TerminalJob {
    id: string;
    title: string;
    output: string[];
    status: JobStatus;
    eventSource: EventSource | null;
}

// Multi-job tracking
export const terminalJobs = writable<Map<string, TerminalJob>>(new Map());
export const activeJobId = writable<string | null>(null);

// Derived: active job
export const activeJob = derived(
    [terminalJobs, activeJobId],
    ([$jobs, $activeId]) => $activeId ? $jobs.get($activeId) || null : null
);

// Derived: job list for tabs
export const jobList = derived(terminalJobs, ($jobs) => Array.from($jobs.values()));

// Derived: active job output as single string
export const terminalText = derived(activeJob, ($job) => $job?.output.join('\n') || '');

// Derived: active job status (for backward compatibility)
export const jobStatus = derived(activeJob, ($job) => $job?.status || 'idle');

// Derived: has any running jobs
export const hasRunningJobs = derived(terminalJobs, ($jobs) => {
    for (const job of $jobs.values()) {
        if (job.status === 'running') return true;
    }
    return false;
});

/**
 * Connect to a job's SSE stream and display output in terminal.
 * Creates a new tab for the job.
 */
export function connectToJobStream(jobId: string, jobTitle: string = 'Job'): void {
    // Open terminal
    terminalOpen.set(true);
    terminalMinimized.set(false);

    // Create new job entry
    const job: TerminalJob = {
        id: jobId,
        title: jobTitle,
        output: [`[${jobTitle}] Starting job ${jobId}...`],
        status: 'running',
        eventSource: null,
    };

    // Connect to SSE endpoint
    const eventSource = new EventSource(`/api/stream/job/${jobId}`);
    job.eventSource = eventSource;

    eventSource.onmessage = (event) => {
        const data = event.data;

        terminalJobs.update(jobs => {
            const currentJob = jobs.get(jobId);
            if (!currentJob) return jobs;

            // Parse special messages
            if (data.startsWith('[EXIT:')) {
                const code = parseInt(data.slice(6, -1), 10);
                currentJob.output = [
                    ...currentJob.output,
                    `[Process exited with code ${code}]`
                ];
                currentJob.status = code === 0 ? 'complete' : 'error';
                disconnectJob(jobId);
                scheduleJobCleanup(jobId);
            } else if (data.startsWith('[COMPLETE]')) {
                currentJob.output = [...currentJob.output, data];
                currentJob.status = 'complete';
                disconnectJob(jobId);
                scheduleJobCleanup(jobId);
            } else if (data.startsWith('[ERROR]')) {
                currentJob.output = [...currentJob.output, data];
                currentJob.status = 'error';
                disconnectJob(jobId);
            } else {
                currentJob.output = [...currentJob.output, data];
            }

            return new Map(jobs);
        });
    };

    eventSource.onerror = () => {
        terminalJobs.update(jobs => {
            const currentJob = jobs.get(jobId);
            if (currentJob) {
                currentJob.output = [...currentJob.output, '[Connection lost]'];
                currentJob.status = 'error';
            }
            return new Map(jobs);
        });
        disconnectJob(jobId);
    };

    // Add job to store and make it active
    terminalJobs.update(jobs => {
        jobs.set(jobId, job);
        return new Map(jobs);
    });
    activeJobId.set(jobId);
}

/**
 * Disconnect a specific job's SSE stream (keep job in list).
 */
function disconnectJob(jobId: string): void {
    terminalJobs.update(jobs => {
        const job = jobs.get(jobId);
        if (job?.eventSource) {
            job.eventSource.close();
            job.eventSource = null;
        }
        return jobs;
    });
}

/**
 * Schedule automatic cleanup of a completed job after delay.
 */
function scheduleJobCleanup(jobId: string, delayMs: number = 5000): void {
    setTimeout(() => {
        const jobs = get(terminalJobs);
        const job = jobs.get(jobId);
        // Only auto-close if still complete (user might have restarted something)
        if (job && (job.status === 'complete' || job.status === 'error')) {
            closeJob(jobId);
        }
    }, delayMs);
}

/**
 * Close and remove a specific job.
 */
export function closeJob(jobId: string): void {
    terminalJobs.update(jobs => {
        const job = jobs.get(jobId);
        if (job?.eventSource) {
            job.eventSource.close();
        }
        jobs.delete(jobId);

        // If we closed the active job, switch to another
        if (get(activeJobId) === jobId) {
            const remaining = Array.from(jobs.keys());
            activeJobId.set(remaining.length > 0 ? remaining[remaining.length - 1] : null);
        }

        // If no jobs left, close terminal
        if (jobs.size === 0) {
            terminalOpen.set(false);
        }

        return new Map(jobs);
    });
}

/**
 * Set the active job tab.
 */
export function setActiveJob(jobId: string): void {
    const jobs = get(terminalJobs);
    if (jobs.has(jobId)) {
        activeJobId.set(jobId);
    }
}

/**
 * Close the terminal pane and all jobs.
 */
export function closeTerminal(): void {
    // Disconnect all jobs
    terminalJobs.update(jobs => {
        for (const job of jobs.values()) {
            if (job.eventSource) {
                job.eventSource.close();
            }
        }
        return new Map();
    });
    activeJobId.set(null);
    terminalOpen.set(false);
}

/**
 * Toggle terminal minimized state.
 */
export function toggleMinimize(): void {
    terminalMinimized.update((m) => !m);
}

/**
 * Clear output for the active job.
 */
export function clearTerminal(): void {
    const currentActiveId = get(activeJobId);
    if (!currentActiveId) return;

    terminalJobs.update(jobs => {
        const job = jobs.get(currentActiveId);
        if (job) {
            job.output = [];
        }
        return new Map(jobs);
    });
}

/**
 * Append a local message to the active job (not from SSE).
 */
export function appendMessage(message: string): void {
    const currentActiveId = get(activeJobId);
    if (!currentActiveId) return;

    terminalJobs.update(jobs => {
        const job = jobs.get(currentActiveId);
        if (job) {
            job.output = [...job.output, message];
        }
        return new Map(jobs);
    });
}
