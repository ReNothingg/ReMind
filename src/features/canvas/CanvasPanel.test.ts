import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import CanvasPanel from './CanvasPanel';

describe('CanvasPanel preview toggle', () => {
    let container: HTMLDivElement | null = null;
    let root: Root | null = null;

    afterEach(() => {
        if (root) {
            act(() => root?.unmount());
        }
        container?.remove();
        root = null;
        container = null;
        vi.useRealTimers();
    });

    it('uses the preview button as an active toggle for HTML documents', () => {
        vi.useFakeTimers();
        const onPreviewToggle = vi.fn();
        const onContentChange = vi.fn();
        const onDraftChange = vi.fn();
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(CanvasPanel, {
                textdoc: {
                    id: 'canvas-html',
                    name: 'index.html',
                    type: 'code/html',
                    content: '<main>Preview</main>',
                    comments: [],
                    updated_at: 1,
                },
                onClose: vi.fn(),
                onContentChange,
                onDraftChange,
                isPreviewActive: true,
                onPreviewToggle,
            }));
        });

        const previewButton = container.querySelector<HTMLButtonElement>('button[aria-pressed="true"]');
        expect(previewButton?.classList.contains('is-active')).toBe(true);
        expect(container.querySelectorAll('.chat-canvas-close-button')).toHaveLength(1);

        act(() => previewButton?.click());
        expect(onPreviewToggle).toHaveBeenCalledOnce();

        const editor = container.querySelector<HTMLTextAreaElement>('.chat-canvas-editor');
        const setValue = Object.getOwnPropertyDescriptor(
            HTMLTextAreaElement.prototype,
            'value'
        )?.set;
        act(() => {
            setValue?.call(editor, '<main>Updated live</main>');
            editor?.dispatchEvent(new Event('input', { bubbles: true }));
        });
        expect(onDraftChange).toHaveBeenLastCalledWith('<main>Updated live</main>');

        act(() => vi.advanceTimersByTime(180));
        expect(onContentChange).toHaveBeenLastCalledWith('<main>Updated live</main>');
    });
});
