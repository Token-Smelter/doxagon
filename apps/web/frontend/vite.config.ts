import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
    // The force-layout Web Worker imports d3-force outside Vite's startup crawl; pre-bundling prevents a mid-suite re-optimization that force-reloads every open test page.
    optimizeDeps: { include: ['d3-force'] },
    server: {
        proxy: {
            // Browser proofs route APIs to fixtures. Port zero cannot host a
            // live service, so an unmocked call fails without touching a vault.
            '/api': process.env.DOXAGON_E2E === '1' ? 'http://127.0.0.1:0' : 'http://127.0.0.1:8000'
        }
    }
});
