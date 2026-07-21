import { defineConfig } from 'vitest/config';

export default defineConfig({
    server: {
        host: '127.0.0.1',
    },
    test: {
        environment: 'jsdom',
        globals: true,
        setupFiles: ['./src/test/setup.ts'],
        include: ['src/**/*.test.ts'],
        coverage: {
            provider: 'v8',
            reporter: ['text', 'lcov'],
            reportsDirectory: './coverage/frontend',
            include: [
                'src/services/api.ts',
                'src/services/auth.ts',
                'src/services/fileService.ts',
                'src/services/http.ts',
                'src/services/openapiClient.ts',
                'src/utils/formatting.ts',
                'src/utils/svgPreview.ts',
            ],
            thresholds: {
                lines: 60,
                functions: 60,
                branches: 50,
                statements: 60,
            },
        },
    }
});
