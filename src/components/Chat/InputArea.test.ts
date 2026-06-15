import React, { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import InputArea from './InputArea';

vi.mock('../../hooks/useFileHandler', () => ({
    useFileHandler: () => ({
        files: [],
        isDragActive: false,
        fileInputRef: { current: null },
        removeFile: vi.fn(),
        clearFiles: vi.fn(),
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
        t: (key: string, fallback?: string) => fallback ?? key,
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
});
