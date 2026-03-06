import { describe, expect, it, vi } from 'vitest';

import { authService } from './auth';

function createJsonResponse(data: unknown, ok = true) {
    return {
        ok,
        status: ok ? 200 : 400,
        json: vi.fn().mockResolvedValue(data),
    };
}

describe('authService coverage', () => {
    it('returns a logged-out state when auth check fails', async () => {
        vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));

        await expect(authService.checkAuth()).resolves.toEqual({
            authenticated: false,
            user: null,
        });
    });

    it('handles login success, api failures, and generic failures', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn()
                .mockResolvedValueOnce(
                    createJsonResponse({
                        message: 'ok',
                        user: { id: 1, username: 'demo', email: 'demo@example.com', is_confirmed: true },
                    }),
                )
                .mockResolvedValueOnce(createJsonResponse({ error: { message: 'wrong password' } }, false))
                .mockRejectedValueOnce(new Error('request crashed')),
        );

        await expect(authService.login('demo@example.com', 'Password1!', null)).resolves.toMatchObject({
            success: true,
            user: expect.objectContaining({ username: 'demo' }),
        });
        await expect(authService.login('demo@example.com', 'bad', null)).resolves.toEqual({
            success: false,
            error: 'wrong password',
        });
        await expect(authService.login('demo@example.com', 'bad', null)).resolves.toEqual({
            success: false,
            error: 'request crashed',
        });
    });

    it('rejects oversized registration fields before fetch', async () => {
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);

        const longValue = 'x'.repeat(101);
        await expect(authService.register(longValue, 'user@example.com', 'Password1!', null)).resolves.toMatchObject({
            success: false,
            error: expect.stringContaining('100'),
        });
        await expect(authService.register('user', `${longValue}@example.com`, 'Password1!', null)).resolves.toMatchObject({
            success: false,
            error: expect.stringContaining('100'),
        });
        await expect(authService.register('user', 'user@example.com', longValue, null)).resolves.toMatchObject({
            success: false,
            error: expect.stringContaining('100'),
        });

        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('registers users with csrf headers and reports api or network failures', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(createJsonResponse({ message: 'created', user_id: 42 }))
            .mockResolvedValueOnce(createJsonResponse({ error: 'already exists' }, false))
            .mockRejectedValueOnce(new Error('network down'));
        vi.stubGlobal('fetch', fetchMock);

        await expect(authService.register('demo', 'demo@example.com', 'Password1!', 'token')).resolves.toEqual({
            success: true,
            message: 'created',
            user_id: 42,
        });
        await expect(authService.register('demo', 'demo@example.com', 'Password1!', 'token')).resolves.toEqual({
            success: false,
            error: 'already exists',
        });
        await expect(authService.register('demo', 'demo@example.com', 'Password1!', 'token')).resolves.toEqual({
            success: false,
            error: 'network down',
        });

        const [, options] = fetchMock.mock.calls[0];
        const headers = options.headers as Record<string, string>;
        expect(headers['X-CSRF-Token']).toBe('test_csrf');
        expect(headers['Content-Type']).toBe('application/json');
    });

    it('logs out and reads profile and settings endpoints', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(createJsonResponse({}))
            .mockResolvedValueOnce(createJsonResponse({ id: 7, username: 'profile-user' }))
            .mockResolvedValueOnce(createJsonResponse({}, false))
            .mockRejectedValueOnce(new Error('profile error'))
            .mockResolvedValueOnce(createJsonResponse({ theme: 'dark' }))
            .mockResolvedValueOnce(createJsonResponse({}, false))
            .mockRejectedValueOnce(new Error('settings error'));
        vi.stubGlobal('fetch', fetchMock);

        await expect(authService.logout()).resolves.toMatchObject({
            success: true,
            message: expect.stringContaining('выход'),
        });
        await expect(authService.getProfile()).resolves.toEqual({ id: 7, username: 'profile-user' });
        await expect(authService.getProfile()).resolves.toEqual({ error: 'Failed to get profile' });
        await expect(authService.getProfile()).resolves.toEqual({ error: 'profile error' });
        await expect(authService.getSettings()).resolves.toEqual({ theme: 'dark' });
        await expect(authService.getSettings()).resolves.toEqual({ error: 'Failed to get settings' });
        await expect(authService.getSettings()).resolves.toEqual({ error: 'settings error' });
    });

    it('updates profile and settings with success and error responses', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(createJsonResponse({ user: { id: 1, username: 'updated' } }))
            .mockResolvedValueOnce(createJsonResponse({ error: 'profile failed' }, false))
            .mockRejectedValueOnce(new Error('profile crash'))
            .mockResolvedValueOnce(createJsonResponse({ settings: { theme: 'light' } }))
            .mockResolvedValueOnce(createJsonResponse({ error: { message: 'settings failed' } }, false))
            .mockRejectedValueOnce(new Error('settings crash'));
        vi.stubGlobal('fetch', fetchMock);

        await expect(authService.updateProfile({ username: 'updated' })).resolves.toEqual({
            success: true,
            user: { id: 1, username: 'updated' },
        });
        await expect(authService.updateProfile({ username: 'updated' })).resolves.toEqual({
            success: false,
            error: 'profile failed',
        });
        await expect(authService.updateProfile({ username: 'updated' })).resolves.toEqual({
            success: false,
            error: 'profile crash',
        });

        await expect(authService.updateSettings({ theme: 'light' })).resolves.toEqual({
            success: true,
            settings: { theme: 'light' },
        });
        await expect(authService.updateSettings({ theme: 'light' })).resolves.toEqual({
            success: false,
            error: 'settings failed',
        });
        await expect(authService.updateSettings({ theme: 'light' })).resolves.toEqual({
            success: false,
            error: 'settings crash',
        });
    });

    it('handles preferences and favorites lifecycle methods', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(createJsonResponse({ preferences: { readingMode: true } }))
            .mockResolvedValueOnce(createJsonResponse({}, false))
            .mockRejectedValueOnce(new Error('preferences failed'))
            .mockResolvedValueOnce(createJsonResponse({ preferences: { readingMode: false } }))
            .mockResolvedValueOnce(createJsonResponse({}, false))
            .mockRejectedValueOnce(new Error('update preferences failed'))
            .mockResolvedValueOnce(createJsonResponse({ favorites: ['s1'] }))
            .mockResolvedValueOnce(createJsonResponse({}, false))
            .mockRejectedValueOnce(new Error('favorites failed'))
            .mockResolvedValueOnce(createJsonResponse({ favorites: ['s1', 's2'] }))
            .mockResolvedValueOnce(createJsonResponse({}, false))
            .mockRejectedValueOnce(new Error('add favorite failed'))
            .mockResolvedValueOnce(createJsonResponse({ favorites: ['s2'] }))
            .mockResolvedValueOnce(createJsonResponse({}, false))
            .mockRejectedValueOnce(new Error('remove favorite failed'));
        vi.stubGlobal('fetch', fetchMock);

        await expect(authService.getPreferences()).resolves.toEqual({ readingMode: true });
        await expect(authService.getPreferences()).resolves.toEqual({});
        await expect(authService.getPreferences()).resolves.toEqual({});

        await expect(authService.updatePreferences({ readingMode: false })).resolves.toEqual({
            success: true,
            preferences: { readingMode: false },
        });
        await expect(authService.updatePreferences({ readingMode: false })).resolves.toEqual({ success: false });
        await expect(authService.updatePreferences({ readingMode: false })).resolves.toEqual({
            success: false,
            error: 'update preferences failed',
        });

        await expect(authService.getFavorites()).resolves.toEqual(['s1']);
        await expect(authService.getFavorites()).resolves.toEqual([]);
        await expect(authService.getFavorites()).resolves.toEqual([]);

        await expect(authService.addFavorite('s2')).resolves.toEqual({
            success: true,
            favorites: ['s1', 's2'],
        });
        await expect(authService.addFavorite('s2')).resolves.toEqual({ success: false });
        await expect(authService.addFavorite('s2')).resolves.toEqual({
            success: false,
            error: 'add favorite failed',
        });

        await expect(authService.removeFavorite('s1')).resolves.toEqual({
            success: true,
            favorites: ['s2'],
        });
        await expect(authService.removeFavorite('s1')).resolves.toEqual({ success: false });
        await expect(authService.removeFavorite('s1')).resolves.toEqual({
            success: false,
            error: 'remove favorite failed',
        });
    });
});
