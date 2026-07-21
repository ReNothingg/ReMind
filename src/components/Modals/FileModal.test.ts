import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import FileModal from './FileModal';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string) => key,
    }),
}));

vi.mock('../../services/fileService', () => ({
    fileService: {
        formatFileSize: () => '48 Bytes',
        isImageFile: () => false,
        isTextFile: () => true,
    },
}));

vi.mock('../../utils/formatting', () => ({
    highlightCode: vi.fn(),
}));

vi.mock('../UI/ModalShell', () => ({
    default: ({ children }: { children: React.ReactNode }) => React.createElement(
        'div',
        { role: 'dialog' },
        children
    ),
}));

describe('FileModal tabs', () => {
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

    it('links tabs to panels and supports roving keyboard navigation', () => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(FileModal, {
                isOpen: true,
                onClose: vi.fn(),
                file: { name: 'preview.html', size: 48, type: 'text/html' },
                content: '<!doctype html><title>Preview</title>',
            }));
        });

        const tabs = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
        expect(tabs).toHaveLength(2);
        expect(tabs.map((tab) => tab.tabIndex)).toEqual([0, -1]);

        const firstPanel = document.getElementById(tabs[0].getAttribute('aria-controls') || '');
        expect(firstPanel?.getAttribute('aria-labelledby')).toBe(tabs[0].id);

        act(() => {
            tabs[0].focus();
            tabs[0].dispatchEvent(new KeyboardEvent('keydown', {
                key: 'ArrowRight',
                bubbles: true,
                cancelable: true,
            }));
        });

        expect(document.activeElement).toBe(tabs[1]);
        expect(tabs.map((tab) => tab.tabIndex)).toEqual([-1, 0]);
        expect(tabs[1].getAttribute('aria-selected')).toBe('true');

        const secondPanel = document.getElementById(tabs[1].getAttribute('aria-controls') || '');
        expect(secondPanel?.hidden).toBe(false);
        expect(secondPanel?.getAttribute('aria-labelledby')).toBe(tabs[1].id);
    });
});
