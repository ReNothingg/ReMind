import { describe, expect, it, vi } from 'vitest';
import { authService } from './auth';

describe('authService', () => {
    it('returns authenticated user from typed auth/check client', async () => {
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            json: async () => ({ authenticated: true, user: { id: 7, username: 'test', email: 'test@example.com', is_confirmed: true } }),
        });
        vi.stubGlobal('fetch', fetchMock);

        const result = await authService.checkAuth();

        expect(result.authenticated).toBe(true);
        expect(result.user?.id).toBe(7);
    });

    it('returns success=true on login', async () => {
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            json: async () => ({ message: 'Успешный вход', user: { id: 1, username: 'demo', email: 'demo@example.com', is_confirmed: true } }),
        });
        vi.stubGlobal('fetch', fetchMock);

        const result = await authService.login('demo@example.com', 'Password1!', null);

        expect(result.success).toBe(true);
        expect(result.user?.username).toBe('demo');
    });

    it('surfaces api error text on login failure', async () => {
        const fetchMock = vi.fn().mockResolvedValue({
            ok: false,
            status: 401,
            json: async () => ({ error: 'Неверный email или пароль' }),
        });
        vi.stubGlobal('fetch', fetchMock);

        const result = await authService.login('demo@example.com', 'bad-pass', null);

        expect(result.success).toBe(false);
        expect(result.error).toBe('Неверный email или пароль');
    });
});
