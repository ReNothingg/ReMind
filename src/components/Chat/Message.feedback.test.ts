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
});
