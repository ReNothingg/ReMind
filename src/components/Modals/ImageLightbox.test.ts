import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import ImageLightbox from './ImageLightbox';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, options?: { defaultValue?: string }) => options?.defaultValue || key,
    }),
}));

describe('ImageLightbox', () => {
    let container: HTMLDivElement | null = null;
    let root: Root | null = null;

    afterEach(() => {
        if (root) {
            act(() => root?.unmount());
        }
        container?.remove();
        container = null;
        root = null;
    });

    it('shows Python artifacts as downloadable previews without generation controls', () => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(ImageLightbox, {
                isOpen: true,
                imageSrc: '/uploads/dashboard.png',
                onClose: vi.fn(),
                currentModel: 'gemini-3.1-flash-lite',
                canRegenerate: false,
                downloadName: 'portfolio_dashboard.png',
            }));
        });

        expect(container.querySelector('[role="dialog"]')).toBeNull();
        expect(document.body.querySelector('[role="dialog"]')).not.toBeNull();
        expect(document.querySelector('#lightboxDownloadBtn')).not.toBeNull();
        expect(document.querySelector('#lightboxRegenerateBtn')).toBeNull();
        expect(document.querySelector('.image-lightbox-style-select')).toBeNull();
        expect(document.querySelector('.image-lightbox-context-card')).toBeNull();
        expect(document.querySelector('.image-lightbox-footer')?.classList.contains('is-preview-only'))
            .toBe(true);
        expect(document.body.textContent).not.toContain('Gemini 3.1 Flash Lite');
    });
});
