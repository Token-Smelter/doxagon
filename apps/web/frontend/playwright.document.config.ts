import { defineConfig, devices } from '@playwright/test';

const port = Number(process.env.DOXAGON_DOCUMENT_PORT ?? 4187);
export default defineConfig({
    testDir: './tests',
    testMatch: ['document-player.spec.ts', 'document-inspection.spec.ts', 'presentation-workspace.spec.ts', 'presentation-styles.spec.ts'],
    workers: 1,
    reporter: 'list',
    use: { baseURL: `http://127.0.0.1:${port}`, trace: 'off', screenshot: 'off' },
    projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
    webServer: {
        command: `uv run --project ../../.. --extra dev python ../../../scripts/preview_document_player.py --port ${port}`,
        url: `http://127.0.0.1:${port}/document-host.html`,
        reuseExistingServer: false,
        timeout: 120_000,
    },
});
