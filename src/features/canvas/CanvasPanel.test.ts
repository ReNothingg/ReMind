import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Utils } from '../../utils/utils';
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
        vi.restoreAllMocks();
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

    it('renders documents as sanitized Markdown and switches to editable raw text', async () => {
        vi.spyOn(Utils, 'renderSvgPreviews').mockImplementation(() => undefined);
        vi.spyOn(Utils, 'renderCharts').mockResolvedValue(undefined);
        vi.spyOn(Utils, 'renderD3').mockResolvedValue(undefined);
        vi.spyOn(Utils, 'renderNomnoml').mockResolvedValue(undefined);
        vi.spyOn(Utils, 'renderMermaid').mockResolvedValue(undefined);
        vi.spyOn(Utils, 'attachDiagramPan').mockImplementation(() => undefined);
        const content = [
            '# Canvas Markdown',
            '',
            '**Bold** and $E = mc^2$',
            '',
            '<img src="x" onerror="alert(1)">',
            '<script>alert(1)</script>',
            '',
            '```chartjs',
            '{"type":"bar","data":{"labels":["A"],"datasets":[{"data":[1]}]}}',
            '```',
            '',
            '```d3',
            '{"type":"line","data":[1,2,3]}',
            '```',
            '',
            '```nomnoml',
            '[Canvas]->[Markdown]',
            '```',
            '',
            '```mermaid',
            'graph TD; A-->B',
            '```',
        ].join('\n');
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        await act(async () => {
            root?.render(React.createElement(CanvasPanel, {
                textdoc: {
                    id: 'canvas-document',
                    name: 'notes.md',
                    type: 'document',
                    content,
                    comments: [],
                    updated_at: 1,
                },
                onClose: vi.fn(),
            }));
        });

        expect(container.querySelector('[data-canvas-view="markdown"]')?.getAttribute('aria-selected'))
            .toBe('true');
        expect(container.querySelector('[data-canvas-view="markdown"]')?.closest('.chat-canvas-header'))
            .not.toBeNull();
        expect(container.querySelector('[data-canvas-view="markdown"]')?.textContent).toBe('');
        expect(container.querySelector('.chat-canvas-view-switcher')).toBeNull();
        expect(container.querySelector('.chat-canvas-markdown h1')?.textContent).toBe('Canvas Markdown');
        expect(container.querySelector<HTMLElement>('.chat-canvas-markdown')?.getAttribute('contenteditable'))
            .toBe('true');
        expect(container.querySelector('.chat-canvas-markdown strong')?.textContent).toBe('Bold');
        expect(container.querySelector('.chat-canvas-markdown .katex')).not.toBeNull();
        expect(container.querySelector('.chart-container')).not.toBeNull();
        expect(container.querySelector('.d3-container')).not.toBeNull();
        expect(container.querySelector('.nomnoml-container')).not.toBeNull();
        expect(container.querySelector('.mermaid-container')).not.toBeNull();
        expect(container.querySelector('.chat-canvas-markdown script')).toBeNull();
        expect(container.querySelector('.chat-canvas-markdown [onerror]')).toBeNull();

        const markdownEditor = container.querySelector<HTMLDivElement>('.chat-canvas-markdown');
        const heading = markdownEditor?.querySelector('h1');
        act(() => {
            if (heading) heading.textContent = 'Edited Canvas Markdown';
            markdownEditor?.dispatchEvent(new InputEvent('input', { bubbles: true }));
            markdownEditor?.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
        });

        const rawButton = container.querySelector<HTMLButtonElement>('[data-canvas-view="raw"]');
        act(() => rawButton?.click());

        expect(rawButton?.getAttribute('aria-selected')).toBe('true');
        expect(container.querySelector<HTMLTextAreaElement>('.chat-canvas-editor')?.value)
            .toContain('# Edited Canvas Markdown');
        expect(container.querySelector('.chat-canvas-markdown')).toBeNull();
    });

    it('keeps the Markdown caret stable while autosave refreshes the canvas document', () => {
        vi.useFakeTimers();
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);
        const onClose = vi.fn();
        let updatedAt = 1;
        const renderPanel = (content: string) => {
            root?.render(React.createElement(CanvasPanel, {
                textdoc: {
                    id: 'canvas-editable-document',
                    name: 'editable.md',
                    type: 'document',
                    content,
                    comments: [],
                    updated_at: updatedAt,
                },
                onClose,
                onContentChange: (nextContent: string) => {
                    updatedAt += 1;
                    renderPanel(nextContent);
                },
            }));
        };

        act(() => renderPanel('# Stable caret'));
        const editor = container.querySelector<HTMLDivElement>('.chat-canvas-markdown');
        const textNode = editor?.querySelector('h1')?.firstChild;
        expect(textNode).toBeInstanceOf(Text);
        if (!(textNode instanceof Text) || !editor) return;

        const selection = window.getSelection();
        const range = document.createRange();
        const originalLength = textNode.length;
        textNode.insertData(originalLength, '!');
        range.setStart(textNode, originalLength + 1);
        range.collapse(true);
        selection?.removeAllRanges();
        selection?.addRange(range);

        act(() => {
            editor.dispatchEvent(new InputEvent('input', { bubbles: true }));
            vi.advanceTimersByTime(200);
        });

        expect(container.querySelector('.chat-canvas-markdown')).toBe(editor);
        expect(selection?.anchorNode).toBe(textNode);
        expect(selection?.anchorOffset).toBe(originalLength + 1);
        expect(editor.querySelector('h1')?.textContent).toBe('Stable caret!');
    });
});
