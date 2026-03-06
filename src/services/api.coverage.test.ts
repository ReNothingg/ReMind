import { describe, expect, it, vi } from 'vitest';

import { apiService, getCsrfToken } from './api';

function createJsonResponse(data: unknown, init: {
    ok?: boolean;
    status?: number;
    statusText?: string;
    headers?: Record<string, string>;
    body?: { getReader: () => { read: () => Promise<{ value?: Uint8Array; done: boolean }> } };
} = {}) {
    return {
        ok: init.ok ?? true,
        status: init.status ?? 200,
        statusText: init.statusText ?? 'OK',
        headers: new Headers(init.headers),
        body: init.body,
        json: vi.fn().mockResolvedValue(data),
        text: vi.fn().mockResolvedValue(typeof data === 'string' ? data : JSON.stringify(data)),
    };
}

describe('apiService coverage', () => {
    it('reads csrf cookies and attaches csrf header for unsafe methods', async () => {
        expect(getCsrfToken()).toBe('test_csrf');

        const fetchMock = vi.fn().mockResolvedValue(createJsonResponse({ ok: true }));
        vi.stubGlobal('fetch', fetchMock);

        await apiService._fetch('/csrf-check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hello: 'world' }),
        });

        const [, options] = fetchMock.mock.calls[0];
        const headers = options.headers as Headers;
        expect(headers.get('X-CSRF-Token')).toBe('test_csrf');
        expect(options.credentials).toBe('include');
    });

    it('returns null for 204 responses and surfaces json api errors', async () => {
        const noContentFetch = vi.fn().mockResolvedValue(createJsonResponse(null, { status: 204 }));
        vi.stubGlobal('fetch', noContentFetch);

        await expect(apiService._fetch('/empty', { method: 'DELETE' })).resolves.toBeNull();

        const errorFetch = vi.fn().mockResolvedValue(
            createJsonResponse(
                { error: 'boom', details: 'from json' },
                { ok: false, status: 418, statusText: 'Teapot' },
            ),
        );
        vi.stubGlobal('fetch', errorFetch);

        await expect(apiService._fetch('/error', { method: 'POST' })).rejects.toMatchObject({
            message: 'boom',
            status: 418,
            data: expect.objectContaining({ error: 'boom', details: 'from json' }),
        });
    });

    it('falls back to text errors and marks serious network failures', async () => {
        const textErrorFetch = vi.fn().mockResolvedValue({
            ok: false,
            status: 500,
            statusText: 'Server Error',
            headers: new Headers(),
            json: vi.fn().mockRejectedValue(new Error('invalid json')),
            text: vi.fn().mockResolvedValue('plain text failure'),
        });
        vi.stubGlobal('fetch', textErrorFetch);

        await expect(apiService._fetch('/text-error', { method: 'POST' })).rejects.toMatchObject({
            message: 'plain text failure',
            status: 500,
            data: expect.objectContaining({ error: 'plain text failure' }),
        });

        const networkError = new Error('NetworkError when attempting to fetch resource.');
        const rejectFetch = vi.fn().mockRejectedValue(networkError);
        vi.stubGlobal('fetch', rejectFetch);

        await expect(apiService._fetch('/network-error')).rejects.toBe(networkError);
        expect(networkError).toMatchObject({ isSerious: true });
    });

    it('parses event streams with widget updates and final metadata', async () => {
        const encoder = new TextEncoder();
        const reader = {
            read: vi.fn()
                .mockResolvedValueOnce({
                    done: false,
                    value: encoder.encode(
                        'data: {"reply_part":"Hello","sources":["s1"],"sessionId":"abc"}\n\n',
                    ),
                })
                .mockResolvedValueOnce({
                    done: false,
                    value: encoder.encode(
                        'data: {"widget_update":{"kind":"status"}}\n\n' +
                        'data: {"reply":"Hello world","end_of_stream":true,"sessionSlug":"hello-world","thinkingTime":12}\n\n',
                    ),
                })
                .mockResolvedValueOnce({ done: true }),
        };

        const fetchMock = vi.fn().mockResolvedValue(
            createJsonResponse(null, {
                headers: { 'content-type': 'text/event-stream' },
                body: { getReader: () => reader },
            }),
        );
        vi.stubGlobal('fetch', fetchMock);

        const onPart = vi.fn();
        const onWidgetUpdate = vi.fn();
        const onComplete = vi.fn();

        await apiService.chat(new FormData(), undefined, { onPart, onWidgetUpdate, onComplete });

        expect(onPart).toHaveBeenCalledWith(expect.objectContaining({ reply_part: 'Hello' }));
        expect(onWidgetUpdate).toHaveBeenCalledWith({ kind: 'status' });
        expect(onComplete).toHaveBeenCalledWith(
            expect.objectContaining({
                reply: 'Hello world',
                sessionId: 'abc',
                sessionSlug: 'hello-world',
                thinkingTime: 12,
                sources: ['s1'],
                widget_update: { kind: 'status' },
            }),
        );
    });

    it('handles plain chat responses, errors, and aborts', async () => {
        const successFetch = vi.fn().mockResolvedValue(
            createJsonResponse(
                { ok: true, reply: 'plain response' },
                { headers: { 'content-type': 'application/json' } },
            ),
        );
        vi.stubGlobal('fetch', successFetch);

        const onComplete = vi.fn();
        await apiService.chat(new FormData(), undefined, { onComplete });
        expect(onComplete).toHaveBeenCalledWith({ ok: true, reply: 'plain response' });

        const onError = vi.fn();
        const failureFetch = vi.fn().mockRejectedValue(new Error('chat failed'));
        vi.stubGlobal('fetch', failureFetch);
        await apiService.chat(new FormData(), undefined, { onError });
        expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'chat failed' }));

        const abortError = new Error('cancelled');
        abortError.name = 'AbortError';
        const abortFetch = vi.fn().mockRejectedValue(abortError);
        vi.stubGlobal('fetch', abortFetch);
        const abortedComplete = vi.fn();
        await apiService.chat(new FormData(), undefined, { onComplete: abortedComplete });
        expect(abortedComplete).toHaveBeenCalledWith({ aborted: true });
    });

    it('supports session list and guest-token session operations', async () => {
        localStorage.setItem('guest_chat_tokens', JSON.stringify({ abc: 'jwt-token', xyz: 'jwt-2' }));

        const fetchMock = vi.fn()
            .mockResolvedValueOnce(
                createJsonResponse({ ok: true, sessions: [], page: 1, page_size: 50, total: 0, has_more: false }),
            )
            .mockResolvedValueOnce(
                createJsonResponse({ ok: true, session_id: 'abc', history: [] }),
            )
            .mockResolvedValueOnce(createJsonResponse({ ok: true }));
        vi.stubGlobal('fetch', fetchMock);

        await apiService.listSessions('abc,xyz');
        await apiService.getSessionHistory('abc');
        await apiService.deleteSession('abc');

        const [listUrl, listOptions] = fetchMock.mock.calls[0];
        expect(listUrl).toContain('/sessions?ids=abc%2Cxyz');
        expect((listOptions.headers as Headers).get('X-Guest-Tokens')).toContain('jwt-token');

        const [, historyOptions] = fetchMock.mock.calls[1];
        expect((historyOptions.headers as Headers).get('Authorization')).toBe('Bearer jwt-token');

        const [, deleteOptions] = fetchMock.mock.calls[2];
        expect((deleteOptions.headers as Headers).get('Authorization')).toBe('Bearer jwt-token');
    });

    it('calls wrapper endpoints for session and privacy actions', async () => {
        const fetchMock = vi.fn().mockResolvedValue(createJsonResponse({ ok: true }));
        vi.stubGlobal('fetch', fetchMock);

        await apiService.toggleShare('s-1', false);
        await apiService.renameSession('s-1', 'Renamed');
        await apiService.canvasAction({ action: 'draw' }, undefined);
        await apiService.getLinkMetadata('https://example.com');
        await apiService.exportPrivacyData();
        await apiService.deletePrivacyData(true);
        await apiService.synthesize('hello');

        const calledUrls = fetchMock.mock.calls.map(([url]) => url);
        expect(calledUrls).toEqual([
            '/sessions/s-1/share',
            '/sessions/s-1/rename',
            '/canvas-action',
            '/get-link-metadata',
            '/api/privacy/export',
            '/api/privacy/delete',
            '/synthesize',
        ]);
    });

    it('returns primary translations and rethrows primary errors when fallback also fails', async () => {
        const successFetch = vi.fn().mockResolvedValue(
            createJsonResponse({ translated_text: 'hola', source_lang: 'en', target_lang: 'es' }),
        );
        vi.stubGlobal('fetch', successFetch);

        await expect(apiService.translate('hello', 'es')).resolves.toMatchObject({
            translated_text: 'hola',
            target_lang: 'es',
        });

        const originalError = new Error('network down');
        const failureFetch = vi.fn().mockRejectedValue(originalError);
        vi.stubGlobal('fetch', failureFetch);

        await expect(apiService.translate('unmapped phrase', 'de')).rejects.toBe(originalError);
    });

    it('loads text resources and falls back to an empty list on fetch errors', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce({
                ok: true,
                text: vi.fn().mockResolvedValue('first\n\nsecond\n'),
            })
            .mockResolvedValueOnce({
                ok: false,
                text: vi.fn(),
            });
        vi.stubGlobal('fetch', fetchMock);

        await expect(apiService.fetchTextResource('/phrases.txt')).resolves.toEqual(['first', 'second']);
        await expect(apiService.fetchTextResource('/missing.txt')).resolves.toEqual([]);
    });
});
