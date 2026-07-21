import { describe, expect, it } from 'vitest';
import { safeGitHubUrl } from './githubUrls';

describe('safeGitHubUrl', () => {
    it('accepts server-provided HTTPS links on github.com', () => {
        expect(safeGitHubUrl('https://github.com/apps/remind')).toBe(
            'https://github.com/apps/remind'
        );
        expect(safeGitHubUrl('https://github.com/settings/installations/123?tab=repositories')).toBe(
            'https://github.com/settings/installations/123?tab=repositories'
        );
    });

    it.each([
        'http://github.com/apps/remind',
        'https://github.com.evil.example/apps/remind',
        'https://evil.example/?next=https://github.com',
        'https://user@github.com/apps/remind',
        'javascript:alert(1)',
        '/github',
        '',
    ])('rejects an unsafe GitHub management URL: %s', (value) => {
        expect(safeGitHubUrl(value)).toBeNull();
    });
});
