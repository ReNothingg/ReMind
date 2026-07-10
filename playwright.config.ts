import { defineConfig } from '@playwright/test';

const e2ePort = Number(process.env.E2E_PORT ?? '5000');
const e2eBaseUrl = `http://127.0.0.1:${e2ePort}`;

export default defineConfig({
    testDir: './tests/e2e',
    timeout: 120_000,
    expect: {
        timeout: 15_000,
    },
    use: {
        baseURL: e2eBaseUrl,
        headless: true,
        trace: 'on-first-retry',
    },
    webServer: {
        command: 'python3 scripts/e2e/run_server.py',
        url: `${e2eBaseUrl}/health`,
        timeout: 120_000,
        reuseExistingServer: false,
    },
});
