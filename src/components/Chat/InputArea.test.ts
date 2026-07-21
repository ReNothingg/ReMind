import React, { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import InputArea from './InputArea';

const addFilesMock = vi.fn();

vi.mock('../../hooks/useFileHandler', () => ({
    useFileHandler: () => ({
        files: [],
        isDragActive: false,
        fileInputRef: { current: null },
        addFiles: addFilesMock,
        removeFile: vi.fn(),
        clearFiles: vi.fn(),
        formatFileSize: vi.fn(() => '8 MB'),
        handleFileInputChange: vi.fn(),
        handleDragEnter: vi.fn(),
        handleDragLeave: vi.fn(),
        handleDragOver: vi.fn(),
        handleDrop: vi.fn(),
    }),
}));

vi.mock('../../context/AuthContext', () => ({
    useAuth: () => ({ isAuthenticated: true }),
}));

vi.mock('../../context/SettingsContext', () => ({
    useSettings: () => ({
        settings: {
            automaticWebSearch: false,
            requireCtrlEnterToSend: false,
        },
    }),
}));

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, options?: string | Record<string, unknown>) => (
            typeof options === 'string' ? options : key
        ),
    }),
}));

vi.mock('../Modals/FileModal', () => ({
    default: () => null,
}));

vi.mock('../UI/FilePreviewCard', () => ({
    default: () => null,
}));

describe('InputArea', () => {
    let container: HTMLDivElement | null = null;
    let root: Root | null = null;

    afterEach(() => {
        if (root) {
            act(() => root?.unmount());
        }
        container?.remove();
        root = null;
        container = null;
        addFilesMock.mockReset();
        vi.restoreAllMocks();
        vi.useRealTimers();
    });

    it('adds a pasted PNG image to the composer', () => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);
        act(() => {
            root?.render(React.createElement(InputArea, {
                initialPrompt: null,
                isLoading: false,
                onStop: vi.fn(),
                onSendMessage: vi.fn(),
                onOpenAuth: vi.fn(),
            }));
        });

        const image = new File(['png'], 'clipboard.png', { type: 'image/png' });
        const pasteEvent = new Event('paste', { bubbles: true, cancelable: true });
        Object.defineProperty(pasteEvent, 'clipboardData', {
            value: {
                items: [{ kind: 'file', type: image.type, getAsFile: () => image }],
            },
        });

        act(() => {
            container?.querySelector('#promptInput')?.dispatchEvent(pasteEvent);
        });

        expect(pasteEvent.defaultPrevented).toBe(true);
        expect(addFilesMock).toHaveBeenCalledWith([image]);
    });

    it('keeps the send button disabled and in send mode while the composer is empty', () => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(InputArea, {
                initialPrompt: null,
                isLoading: false,
                onStop: vi.fn(),
                onSendMessage: vi.fn(),
                onOpenAuth: vi.fn(),
            }));
        });

        const sendButton = container.querySelector<HTMLButtonElement>('#sendButton');
        const input = container.querySelector<HTMLTextAreaElement>('#promptInput');

        expect(sendButton?.disabled).toBe(true);
        expect(sendButton?.classList.contains('send-mode-button')).toBe(true);
        expect(sendButton?.classList.contains('audio-link-button')).toBe(false);

        act(() => {
            const valueSetter = Object.getOwnPropertyDescriptor(
                HTMLTextAreaElement.prototype,
                'value'
            )?.set;
            valueSetter?.call(input, 'Hello');
            input?.dispatchEvent(new Event('input', { bubbles: true }));
        });

        expect(sendButton?.disabled).toBe(false);
    });

    it('clears a URL-provided initial prompt after sending even when the composer remounts', () => {
        const onSendMessage = vi.fn();

        function Harness() {
            const [initialPrompt, setInitialPrompt] = useState<string | null>('Queued prompt');
            const [composerKey, setComposerKey] = useState(0);

            return React.createElement(InputArea, {
                key: composerKey,
                initialPrompt,
                isLoading: false,
                onStop: vi.fn(),
                onSendMessage: (...args: unknown[]) => {
                    onSendMessage(...args);
                    setComposerKey((current) => current + 1);
                },
                onInitialPromptConsumed: () => setInitialPrompt(null),
                onOpenAuth: vi.fn(),
            });
        }

        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(Harness));
        });

        const input = container.querySelector<HTMLTextAreaElement>('#promptInput');
        const sendButton = container.querySelector<HTMLButtonElement>('#sendButton');

        expect(input?.value).toBe('Queued prompt');

        act(() => {
            sendButton?.click();
        });

        expect(onSendMessage).toHaveBeenCalledWith(
            'Queued prompt',
            [],
            expect.objectContaining({
                autoWebSearch: false,
                censorship: false,
                webSearch: false,
            })
        );
        expect(container.querySelector<HTMLTextAreaElement>('#promptInput')?.value).toBe('');
    });

    it('shows the quote action again for a second text selection', () => {
        vi.useFakeTimers();
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(InputArea, {
                initialPrompt: null,
                isLoading: false,
                onStop: vi.fn(),
                onSendMessage: vi.fn(),
                onOpenAuth: vi.fn(),
            }));
        });

        const message = document.createElement('div');
        message.className = 'ai-message';
        const messageText = document.createElement('div');
        messageText.className = 'message-text';
        const selectedNode = document.createTextNode('First selection');
        messageText.appendChild(selectedNode);
        message.appendChild(messageText);
        document.body.appendChild(message);

        let selectedText = 'First selection';
        const removeAllRanges = vi.fn();
        vi.spyOn(window, 'getSelection').mockImplementation(() => ({
            isCollapsed: false,
            rangeCount: 1,
            toString: () => selectedText,
            getRangeAt: () => ({
                commonAncestorContainer: selectedNode,
                getBoundingClientRect: () => ({
                    left: 100,
                    right: 220,
                    top: 100,
                    bottom: 120,
                    width: 120,
                    height: 20,
                    x: 100,
                    y: 100,
                    toJSON: () => ({}),
                }),
            }),
            removeAllRanges,
        } as unknown as Selection));

        act(() => {
            messageText.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
            vi.advanceTimersByTime(10);
        });

        const firstQuoteButton = document.body.querySelector<HTMLButtonElement>('.quote-action-button');
        expect(firstQuoteButton?.classList.contains('visible')).toBe(true);

        act(() => firstQuoteButton?.click());
        selectedText = 'Second selection';

        act(() => {
            messageText.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
            vi.advanceTimersByTime(10);
        });

        const secondQuoteButton = document.body.querySelector<HTMLButtonElement>('.quote-action-button');
        expect(secondQuoteButton?.isConnected).toBe(true);
        expect(secondQuoteButton?.classList.contains('visible')).toBe(true);

        act(() => secondQuoteButton?.click());

        expect(Array.from(container.querySelectorAll('.quote-item blockquote')).map((item) => item.textContent))
            .toEqual(['First selection', 'Second selection']);

        message.remove();
    });
});
