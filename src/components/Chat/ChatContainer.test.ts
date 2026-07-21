import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import ChatContainer from './ChatContainer';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('./Message', () => ({
    default: ({ message }: { message: { id: string } }) => React.createElement(
        'div',
        { className: 'message', 'data-message-id': message.id },
        message.id
    ),
}));

describe('ChatContainer motion preferences', () => {
    let container: HTMLDivElement | null = null;
    let root: Root | null = null;
    const originalMatchMedia = window.matchMedia;
    const originalScrollIntoView = Element.prototype.scrollIntoView;

    afterEach(() => {
        if (root) {
            act(() => root?.unmount());
        }
        container?.remove();
        container = null;
        root = null;
        Object.defineProperty(window, 'matchMedia', {
            configurable: true,
            writable: true,
            value: originalMatchMedia,
        });
        Object.defineProperty(Element.prototype, 'scrollIntoView', {
            configurable: true,
            writable: true,
            value: originalScrollIntoView,
        });
    });

    it('uses instant scrolling when reduced motion is requested', () => {
        const scrollIntoView = vi.fn();
        Object.defineProperty(window, 'matchMedia', {
            configurable: true,
            writable: true,
            value: vi.fn(() => ({ matches: true })),
        });
        Object.defineProperty(Element.prototype, 'scrollIntoView', {
            configurable: true,
            writable: true,
            value: scrollIntoView,
        });

        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(ChatContainer, {
                history: [{ id: 'answer', role: 'assistant' }],
                isLoading: false,
                onRegenerate: vi.fn(),
                onEdit: vi.fn(),
                onSwitchVariant: vi.fn(),
                onBeatboxStateChange: vi.fn(),
            }));
        });

        expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'auto', block: 'end' });
    });
});
