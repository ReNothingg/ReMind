import { describe, expect, it, vi } from 'vitest';
import { apiService } from './api';

describe('apiService', () => {
    it('builds typed /sessions request with guest tokens and pagination', async () => {
        localStorage.setItem('guest_chat_tokens', JSON.stringify({ s1: 'token-1' }));

        const fetchMock = vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            json: async () => ({ ok: true, sessions: [], page: 2, page_size: 10, total: 0, has_more: false }),
        });
        vi.stubGlobal('fetch', fetchMock);

        await apiService.listSessions({ idsQuery: 's1,s2', page: 2, pageSize: 10 });

        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [url, options] = fetchMock.mock.calls[0];
        expect(url).toContain('/sessions?');
        expect(url).toContain('ids=s1%2Cs2');
        expect(url).toContain('page=2');
        expect(url).toContain('page_size=10');

        const headers = options.headers as Headers;
        expect(headers.get('X-Guest-Tokens')).toContain('token-1');
    });

    it('falls back to local translation dictionary when API is unavailable', async () => {
        const fetchMock = vi.fn().mockRejectedValue(new Error('network down'));
        vi.stubGlobal('fetch', fetchMock);

        const result = await apiService.translate('hello world', 'ru');

        expect(result.fallback).toBe(true);
        expect(result.translated_text).toContain('привет');
        expect(result.translated_text).toContain('мир');
    });

    it('adds guest bearer token for session history', async () => {
        localStorage.setItem('guest_chat_tokens', JSON.stringify({ abc: 'jwt-token' }));

        const fetchMock = vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            json: async () => ({ ok: true, session_id: 'abc', history: [] }),
        });
        vi.stubGlobal('fetch', fetchMock);

        await apiService.getSessionHistory('abc');

        const [, options] = fetchMock.mock.calls[0];
        const headers = options.headers as Headers;
        expect(headers.get('Authorization')).toBe('Bearer jwt-token');
    });

    it('keeps guest authentication for chat turns and branch selection', async () => {
        localStorage.setItem('guest_chat_tokens', JSON.stringify({ abc: 'jwt-token' }));
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            headers: new Headers({ 'content-type': 'application/json' }),
            json: async () => ({ ok: true, session_id: 'abc', history: [] }),
        });
        vi.stubGlobal('fetch', fetchMock);

        const formData = new FormData();
        formData.append('session_id', 'abc');
        await apiService.chat(formData);
        await apiService.selectSessionBranch('abc', 'a_1');

        const chatHeaders = fetchMock.mock.calls[0][1].headers as Headers;
        const branchHeaders = fetchMock.mock.calls[1][1].headers as Headers;
        expect(chatHeaders.get('Authorization')).toBe('Bearer jwt-token');
        expect(branchHeaders.get('Authorization')).toBe('Bearer jwt-token');
    });

    it('preserves structured chat API errors instead of stringifying the payload', async () => {
        const onError = vi.fn();
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: false,
            status: 409,
            headers: new Headers({ 'content-type': 'application/json' }),
            json: async () => ({
                ok: false,
                error: { code: 'message_id_conflict', message: 'Message ID already exists' },
            }),
        }));
        const formData = new FormData();
        formData.append('session_id', 'abc');

        await apiService.chat(formData, undefined, { onError });

        expect(onError).toHaveBeenCalledWith(expect.objectContaining({
            message: 'Message ID already exists',
            status: 409,
        }));
    });
});
