import { defineConfig } from '@playwright/test';

export default defineConfig({
    testDir: './tests/e2e',
    timeout: 120_000,
    expect: {
        timeout: 15_000,
    },
    use: {
        baseURL: 'http://127.0.0.1:5000',
        headless: true,
        trace: 'on-first-retry',
    },
    webServer: {
        command: 'python scripts/e2e/run_server.py',
        url: 'http://127.0.0.1:5000/health',
        timeout: 120_000,
        reuseExistingServer: !process.env.CI,
    },
});
