import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import CanvasHtmlPreview from './CanvasHtmlPreview';

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
    });

    it('loads the site in an isolated inline frame', () => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(CanvasHtmlPreview, {
                html: '<main>Preview</main>',
            }));
        });

        const frame = container.querySelector('iframe');
        expect(container.querySelector('.canvas-site-preview')).not.toBeNull();
        expect(frame?.getAttribute('src')).toBe('/html-preview.html');
        expect(frame?.getAttribute('sandbox')).toBe('allow-forms allow-scripts');
        expect(frame?.getAttribute('sandbox')).not.toContain('allow-same-origin');

        if (!frame?.contentWindow) {
            throw new Error('Preview frame window is unavailable');
        }
        const postMessage = vi.spyOn(frame.contentWindow, 'postMessage');
        frame.dataset.previewReady = 'true';

        act(() => {
            root?.render(React.createElement(CanvasHtmlPreview, {
                html: '<main>Updated live</main>',
            }));
        });

        expect(postMessage).toHaveBeenLastCalledWith({
            type: 'remind:html-preview',
            html: '<main>Updated live</main>',
        }, '*');
    });
});
