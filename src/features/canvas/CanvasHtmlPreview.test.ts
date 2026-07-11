import React, { act, createRef } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import CanvasHtmlPreview, { type CanvasHtmlPreviewHandle } from './CanvasHtmlPreview';

describe('CanvasHtmlPreview', () => {
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

    it('loads the site in an isolated inline frame', () => {
        vi.useFakeTimers();
        const previewRef = createRef<CanvasHtmlPreviewHandle>();
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(CanvasHtmlPreview, {
                ref: previewRef,
                html: '<main>Preview</main>',
            }));
        });

        const frame = container.querySelector('iframe');
        expect(container.querySelector('.canvas-site-preview')).not.toBeNull();
        expect(frame?.getAttribute('src')).toBe('/html-preview.html');
        expect(frame?.getAttribute('sandbox')).toBe('allow-scripts');
        expect(frame?.getAttribute('sandbox')).not.toContain('allow-same-origin');

        if (!frame?.contentWindow) {
            throw new Error('Preview frame window is unavailable');
        }
        const postMessage = vi.spyOn(frame.contentWindow, 'postMessage');
        frame.dataset.previewReady = 'true';

        act(() => {
            root?.render(React.createElement(CanvasHtmlPreview, {
                ref: previewRef,
                html: '<main>Updated live</main>',
            }));
        });

        expect(postMessage).toHaveBeenLastCalledWith({
            type: 'remind:html-preview',
            html: '<main>Updated live</main>',
        }, '*');

        act(() => previewRef.current?.render('<main>Typed draft</main>'));
        expect(postMessage).not.toHaveBeenLastCalledWith({
            type: 'remind:html-preview',
            html: '<main>Typed draft</main>',
        }, '*');
        act(() => vi.advanceTimersByTime(90));
        expect(postMessage).toHaveBeenLastCalledWith({
            type: 'remind:html-preview',
            html: '<main>Typed draft</main>',
        }, '*');
    });
});
