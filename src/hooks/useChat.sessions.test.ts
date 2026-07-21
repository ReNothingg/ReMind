import React, { act, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../context/SettingsContext', () => ({
    useSettings: () => ({ settings: { automaticWebSearch: false } }),
}));

vi.mock('../context/AuthContext', () => ({
    useAuth: () => ({
        isAuthenticated: true,
        user: { id: 'test-user' },
        loading: false,
        checkAuth: vi.fn().mockResolvedValue({ authenticated: true }),
    }),
}));

vi.mock('../services/reliability', () => ({
    enqueueChatMessage: vi.fn(),
    listQueuedChatMessages: vi.fn().mockResolvedValue([]),
    reconcileQueuedChatOwner: vi.fn().mockResolvedValue(undefined),
    removeQueuedChatMessage: vi.fn().mockResolvedValue(undefined),
}));

import { apiService } from '../services/api';
import { fileService } from '../services/fileService';
import { useChat } from './useChat';

describe('useChat session multitasking', () => {
    let container: HTMLDivElement;
    let root: Root;
    let latest: ReturnType<typeof useChat>;

    beforeEach(() => {
        window.history.replaceState({}, '', '/');
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        function Harness() {
            const value = useChat();
            useEffect(() => {
                latest = value;
            }, [value]);
            return null;
        }

        act(() => root.render(React.createElement(Harness)));
    });

    afterEach(() => {
        act(() => root.unmount());
        container.remove();
    });

    it('activates the destination immediately and ignores a stale session load', async () => {
        let resolveFirst: (value: unknown) => void = () => undefined;
        let resolveSecond: (value: unknown) => void = () => undefined;
        const first = new Promise((resolve) => { resolveFirst = resolve; });
        const second = new Promise((resolve) => { resolveSecond = resolve; });

        vi.spyOn(apiService, 'getSessionHistory')
            .mockReturnValueOnce(first as ReturnType<typeof apiService.getSessionHistory>)
            .mockReturnValueOnce(second as ReturnType<typeof apiService.getSessionHistory>);

        let firstLoad: ReturnType<typeof latest.loadSession>;
        act(() => {
            firstLoad = latest.loadSession('session-a', { historyMode: 'none' });
        });
        expect(latest.currentSessionId).toBe('session-a');

        let secondLoad: ReturnType<typeof latest.loadSession>;
        act(() => {
            secondLoad = latest.loadSession('session-b', { historyMode: 'none' });
        });
        expect(latest.currentSessionId).toBe('session-b');

        await act(async () => {
            resolveFirst({
                session_id: 'session-a',
                history: [{ id: 'a1', role: 'model', parts: [{ text: 'stale A' }] }],
            });
            await firstLoad;
        });
        expect(latest.currentSessionId).toBe('session-b');
        expect(latest.history).toEqual([]);

        await act(async () => {
            resolveSecond({
                session_id: 'session-b',
                history: [{ id: 'b1', role: 'model', parts: [{ text: 'fresh B' }] }],
            });
            await secondLoad;
        });
        expect(latest.currentSessionId).toBe('session-b');
        expect(latest.history.map((message) => message.content)).toEqual(['fresh B']);
    });

    it('shows a new conversation before an attachment finishes preprocessing', async () => {
        let finishInspection: (value: '') => void = () => undefined;
        vi.spyOn(fileService, 'detectImageMimeFromFile').mockReturnValue(
            new Promise<''>((resolve) => { finishInspection = resolve; })
        );
        vi.spyOn(apiService, 'chat').mockResolvedValue(undefined);
        const attachment = new File(['payload'], 'payload.bin', {
            type: 'application/octet-stream',
        });

        let sending: ReturnType<typeof latest.sendMessage>;
        act(() => {
            sending = latest.sendMessage('inspect this', [attachment]);
        });

        expect(latest.history).toHaveLength(2);
        expect(latest.history[0]).toMatchObject({
            role: 'user',
            content: 'inspect this',
        });
        expect(latest.history[1]).toMatchObject({
            role: 'model',
            isLoading: true,
        });

        await act(async () => {
            finishInspection('');
            await sending;
        });
    });

    it('reopens a locally generating chat without requesting history that is not persisted yet', async () => {
        let finishStream: () => void = () => undefined;
        vi.spyOn(apiService, 'chat').mockReturnValue(
            new Promise<void>((resolve) => { finishStream = resolve; })
        );
        const historySpy = vi.spyOn(apiService, 'getSessionHistory').mockResolvedValue({
            ok: true,
            session_id: 'session-b',
            history: [{ id: 'b1', role: 'model', parts: [{ text: 'session B' }] }],
        });

        let sending: ReturnType<typeof latest.sendMessage>;
        act(() => {
            sending = latest.sendMessage('background task');
        });
        const generatingSessionId = latest.currentSessionId;
        expect(generatingSessionId).toBeTruthy();

        await act(async () => {
            await latest.loadSession('session-b');
        });
        expect(historySpy).toHaveBeenCalledTimes(1);

        await act(async () => {
            await latest.loadSession(generatingSessionId);
        });
        expect(historySpy).toHaveBeenCalledTimes(1);
        expect(latest.isLoading).toBe(true);
        expect(latest.history.map((message) => message.content)).toContain('background task');

        await act(async () => {
            finishStream();
            await sending;
        });
    });

    it('keeps a streaming session alive without writing its chunks into another chat', async () => {
        vi.spyOn(apiService, 'getSessionHistory').mockImplementation(async (sessionId) => ({
            ok: true,
            session_id: sessionId,
            history: [{ id: `${sessionId}-seed`, role: 'model', parts: [{ text: `seed ${sessionId}` }] }],
        }));

        let streamHandlers: {
            onPart: (data: { reply_part: string }) => void;
            onComplete: (data: { history: unknown[] }) => void;
        } | null = null;
        let finishStream: (value: unknown) => void = () => undefined;
        vi.spyOn(apiService, 'chat').mockImplementation((_formData, _signal, handlers) => {
            streamHandlers = handlers as typeof streamHandlers;
            return new Promise((resolve) => { finishStream = resolve; });
        });

        await act(async () => {
            await latest.loadSession('session-a');
        });

        let sending: ReturnType<typeof latest.sendMessage>;
        await act(async () => {
            sending = latest.sendMessage('question A');
            await Promise.resolve();
        });
        expect(latest.sessionActivity['session-a']?.status).toBe('generating');

        await act(async () => {
            await latest.loadSession('session-b');
        });
        expect(latest.history.map((message) => message.content)).toEqual(['seed session-b']);

        act(() => {
            streamHandlers?.onPart({ reply_part: 'background answer A' });
        });
        expect(latest.currentSessionId).toBe('session-b');
        expect(latest.history.map((message) => message.content)).toEqual(['seed session-b']);

        await act(async () => {
            await latest.loadSession('session-a');
        });
        expect(latest.isLoading).toBe(true);
        expect(latest.history.map((message) => message.content)).toContain('background answer A');

        await act(async () => {
            streamHandlers?.onComplete({
                history: [
                    { id: 'session-a-seed', role: 'model', parts: [{ text: 'seed session-a' }] },
                    { id: 'session-a-user', role: 'user', parts: [{ text: 'question A' }] },
                    { id: 'session-a-answer', role: 'model', parts: [{ text: 'background answer A' }] },
                ],
            });
            finishStream({});
            await sending;
        });
        expect(latest.isLoading).toBe(false);
    });
});
