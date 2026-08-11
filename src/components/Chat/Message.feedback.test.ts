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

import { apiService } from '../../services/api';
import Message from './Message';

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
