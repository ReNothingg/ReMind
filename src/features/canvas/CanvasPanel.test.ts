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
        const onPreviewToggle = vi.fn();
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
                isPreviewActive: true,
                onPreviewToggle,
            }));
        });

        const previewButton = container.querySelector<HTMLButtonElement>('button[aria-pressed="true"]');
        expect(previewButton?.classList.contains('is-active')).toBe(true);
        expect(container.querySelectorAll('.chat-canvas-close-button')).toHaveLength(1);
        expect(container.querySelector('.chat-canvas-toolbar')).toBeNull();
        expect(container.querySelector('.chat-canvas-header .chat-canvas-type-label')).not.toBeNull();
        expect(container.querySelectorAll('.chat-canvas-header .chat-canvas-icon-button'))
            .toHaveLength(4);

        act(() => previewButton?.click());
        expect(onPreviewToggle).toHaveBeenCalledOnce();
    });

    it('shows line numbers, syntax highlighting, and working code-fold controls', async () => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(CanvasPanel, {
                textdoc: {
                    id: 'canvas-python',
                    name: 'rich_bot.py',
                    type: 'code/python',
                    content: 'def example():\n    first()\n    second()',
                    comments: [],
                    updated_at: 1,
                },
                onClose: vi.fn(),
            }));
        });

        expect(container.querySelector('.cm-lineNumbers')).not.toBeNull();
        expect(container.querySelector('.cm-foldGutter')).not.toBeNull();
        expect(container.querySelector('.cm-content')?.textContent).toContain('def example():');
        expect(container.querySelector('.chat-canvas-header')?.textContent).not.toContain('3 lines');
        expect(container.querySelector('.chat-canvas-toolbar')).toBeNull();

        await vi.waitFor(() => {
            expect(container?.querySelector('.chat-canvas-fold-marker.is-open')).not.toBeNull();
        });

        const openMarker = container.querySelector<HTMLElement>('.chat-canvas-fold-marker.is-open');
        expect(openMarker?.getAttribute('aria-label')).toBe('codeBlock.collapse');
        act(() => openMarker?.dispatchEvent(new MouseEvent('click', { bubbles: true })));

        await vi.waitFor(() => {
            expect(container?.querySelector('.chat-canvas-fold-marker.is-closed')).not.toBeNull();
            expect(container?.querySelector('.cm-foldPlaceholder')).not.toBeNull();
        });
    });

    it('keeps the line-number DOM bounded for very large documents', () => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(CanvasPanel, {
                textdoc: {
                    id: 'canvas-large',
                    name: 'large.py',
                    type: 'code/python',
                    content: Array.from({ length: 5_000 }, () => '').join('\n'),
                    comments: [],
                    updated_at: 1,
                },
                onClose: vi.fn(),
            }));
        });

        const renderedLineNumbers = container.querySelectorAll(
            '.cm-lineNumbers .cm-gutterElement'
        );
        expect(renderedLineNumbers.length).toBeGreaterThan(0);
        expect(renderedLineNumbers.length).toBeLessThan(100);
    });
});
