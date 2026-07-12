import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getDeviceId, getRemoteDraft, saveRemoteDraft } from './reliability';

describe('reliability service', () => {
    beforeEach(() => {
        localStorage.clear();
        vi.restoreAllMocks();
    });

    it('keeps a stable per-device identifier', () => {
        const first = getDeviceId();
        expect(first).toBeTruthy();
        expect(getDeviceId()).toBe(first);
    });

    it('loads and saves a revisioned synchronized draft', async () => {
        const fetchMock = vi.spyOn(globalThis, 'fetch')
            .mockResolvedValueOnce(new Response(JSON.stringify({
                draft: { content: 'remote', revision: 2, updated_at: 10, device_id: 'a', session_id: null },
            }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
            .mockResolvedValueOnce(new Response(JSON.stringify({
                draft: { content: 'next', revision: 3, updated_at: 11, device_id: 'a', session_id: null },
            }), { status: 200, headers: { 'Content-Type': 'application/json' } }));

        expect((await getRemoteDraft())?.revision).toBe(2);
        expect((await saveRemoteDraft('next', null, 2)).revision).toBe(3);
        expect(fetchMock.mock.calls[1][1]?.method).toBe('PUT');
    });
});
