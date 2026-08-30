import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../../context/SettingsContext', () => ({
    useSettings: () => ({
        settings: {
            renderMarkdown: false,
            codeWrap: true,
            theme: 'dark',
        },
    }),
}));

vi.mock('../../hooks/useAudio', () => ({
    useAudio: () => ({
        isVisible: false,
        isLoading: false,
        isError: false,
        isPlaying: false,
        isReady: false,
        currentTime: 0,
        totalDuration: 0,
        waveformPoints: [],
        speak: vi.fn(),
        togglePlayback: vi.fn(),
        seek: vi.fn(),
    }),
}));

vi.mock('../../context/AuthContext', () => ({
    useAuth: () => ({ isAuthenticated: true }),
}));

import { apiService } from '../../services/api';
import Message from './Message';
import {
    filterRedundantAutoCapturedImages,
    stripAttachedArtifactMarkdownImages,
} from './imageArtifacts';

describe('Message feedback actions', () => {
    let container: HTMLDivElement;
    let root: Root;

    beforeEach(() => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);
    });

    afterEach(() => {
        act(() => root.unmount());
        container.remove();
        delete window.openImageLightbox;
    });

    it('keeps an explicitly saved Python image instead of its automatic figure snapshot', () => {
        const images = filterRedundantAutoCapturedImages([
            {
                url_path: '/uploads/auto.png',
                original_name: 'figure-1.png',
                source: 'python',
            },
            {
                url_path: '/uploads/explicit.png',
                original_name: 'number_one.png',
                source: 'python',
            },
        ]);

        expect(images).toHaveLength(1);
        expect(images[0].original_name).toBe('number_one.png');
    });

    it('keeps multiple automatic figures when there is no explicit image artifact', () => {
        const images = filterRedundantAutoCapturedImages([
            { original_name: 'figure-1.png', source: 'python' },
            { original_name: 'figure-2.png', source: 'python' },
        ]);

        expect(images).toHaveLength(2);
    });

    it('removes Markdown images already represented by an attachment', () => {
        const content = 'Done\n\n![result](figure-1.png)\n\n![external](https://example.com/x.png)';
        const stripped = stripAttachedArtifactMarkdownImages(content, [
            { original_name: 'figure-1.png', source: 'python' },
        ]);

        expect(stripped).not.toContain('![result]');
        expect(stripped).toContain('![external](https://example.com/x.png)');
    });

    it('lets the opposite reaction replace an accidental rating', async () => {
        const submitFeedback = vi.spyOn(apiService, 'submitAIResponseFeedback')
            .mockResolvedValue({ feedback: { rating: 'like' } });

        act(() => {
            root.render(React.createElement(Message, {
                message: {
                    id: 'assistant-1',
                    role: 'model',
                    content: 'Useful answer',
                },
                sessionId: 'session-1',
                onRegenerate: undefined,
                onEdit: undefined,
                onSwitchVariant: undefined,
                onBeatboxStateChange: undefined,
            }));
        });

        const likeButton = container.querySelector<HTMLButtonElement>(
            '[aria-label="chat.feedback.like"]'
        );
        expect(likeButton).not.toBeNull();

        await act(async () => {
            likeButton?.click();
            await Promise.resolve();
        });

        expect(submitFeedback).toHaveBeenLastCalledWith(expect.objectContaining({ rating: 'like' }));
        expect(container.querySelector('[aria-label="chat.feedback.like"]')).toBeNull();
        expect(container.querySelector('[aria-label="chat.feedback.dislike"]')).not.toBeNull();
        expect(container.querySelector('.feedback-like-confetti')).not.toBeNull();

        act(() => {
            container.querySelector<HTMLButtonElement>('[aria-label="chat.feedback.dislike"]')?.click();
        });
        submitFeedback.mockResolvedValueOnce({ feedback: { rating: 'dislike' } });
        await act(async () => {
            container.querySelector<HTMLButtonElement>('.ai-feedback-submit')?.click();
            await Promise.resolve();
        });

        expect(submitFeedback).toHaveBeenLastCalledWith(expect.objectContaining({ rating: 'dislike' }));
        expect(container.querySelector('[aria-label="chat.feedback.dislike"]')).toBeNull();
        expect(container.querySelector('[aria-label="chat.feedback.like"]')).not.toBeNull();

        submitFeedback.mockResolvedValueOnce({ feedback: { rating: 'like' } });
        await act(async () => {
            container.querySelector<HTMLButtonElement>('[aria-label="chat.feedback.like"]')?.click();
            await Promise.resolve();
        });

        expect(submitFeedback).toHaveBeenLastCalledWith(expect.objectContaining({ rating: 'like' }));
        expect(container.querySelector('[aria-label="chat.feedback.like"]')).toBeNull();
        expect(container.querySelector('[aria-label="chat.feedback.dislike"]')).not.toBeNull();
        expect(container.querySelector('.feedback-like-confetti')).not.toBeNull();
    });

    it('renders assistant images after the streamed thinking block', () => {
        act(() => {
            root.render(React.createElement(Message, {
                message: {
                    id: 'assistant-with-image',
                    role: 'model',
                    content: 'Finished answer',
                    images: ['/uploads/result.png'],
                    isLoading: true,
                    thinking: {
                        id: 'thought-1',
                        status: 'complete',
                        content: '**Done**\nImage prepared.',
                        openTime: 100,
                        closeTime: 200,
                    },
                },
                sessionId: 'session-1',
                onRegenerate: undefined,
                onEdit: undefined,
                onSwitchVariant: undefined,
                onBeatboxStateChange: undefined,
            }));
        });

        const thought = container.querySelector('.think-block-wrapper');
        const images = container.querySelector('.message-image-grid');
        expect(thought).not.toBeNull();
        expect(images).not.toBeNull();
        expect(thought?.compareDocumentPosition(images as Node) & Node.DOCUMENT_POSITION_FOLLOWING)
            .toBeTruthy();
    });

    it('opens Python image artifacts in preview-only mode', () => {
        const openImageLightbox = vi.fn();
        window.openImageLightbox = openImageLightbox;

        act(() => {
            root.render(React.createElement(Message, {
                message: {
                    id: 'assistant-python-image',
                    role: 'model',
                    content: 'Dashboard created',
                    images: [{
                        url_path: '/uploads/dashboard.png',
                        original_name: 'portfolio_dashboard.png',
                        source: 'python',
                    }],
                },
                sessionId: 'session-1',
                onRegenerate: undefined,
                onEdit: undefined,
                onSwitchVariant: undefined,
                onBeatboxStateChange: undefined,
            }));
        });

        act(() => {
            container.querySelector<HTMLButtonElement>('.message-image-button')?.click();
        });

        expect(openImageLightbox).toHaveBeenCalledWith(
            expect.stringContaining('/uploads/dashboard.png'),
            'assistant-python-image',
            {
                canRegenerate: false,
                downloadName: 'portfolio_dashboard.png',
            },
        );
    });

    it('renders assistant file artifacts after the thinking block', () => {
        act(() => {
            root.render(React.createElement(Message, {
                message: {
                    id: 'assistant-with-file',
                    role: 'model',
                    content: 'Audit complete',
                    files: [{
                        file: {
                            url_path: '/uploads/audit.pdf',
                            original_name: 'audit.pdf',
                            mime_type: 'application/pdf',
                            size: 2048,
                        },
                    }],
                    isLoading: true,
                    thinking: {
                        id: 'thought-with-file',
                        status: 'complete',
                        content: '**Validated**\nThe report is complete.',
                        openTime: 100,
                        closeTime: 200,
                    },
                },
                sessionId: 'session-1',
                onRegenerate: undefined,
                onEdit: undefined,
                onSwitchVariant: undefined,
                onBeatboxStateChange: undefined,
            }));
        });

        const thought = container.querySelector('.think-block-wrapper');
        const files = container.querySelector('.message-attachments');
        expect(thought).not.toBeNull();
        expect(files).not.toBeNull();
        expect(thought?.compareDocumentPosition(files as Node) & Node.DOCUMENT_POSITION_FOLLOWING)
            .toBeTruthy();
    });
});
