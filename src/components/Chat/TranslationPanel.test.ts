import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import TranslationPanel from './TranslationPanel';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const translateMock = vi.hoisted(() => vi.fn());

vi.mock('../../services/api', () => ({
    apiService: { translate: translateMock },
}));

vi.mock('react-i18next', () => ({
    useTranslation: (() => {
        const t = (key: string) => ({
            'translationPanel.close': 'Close',
            'translationPanel.fallbackNotice': 'Translated using a fallback service',
            'translationPanel.languages.russian': 'Russian',
            'translationPanel.loading': 'Translating',
            'translationPanel.translateAction': 'Translate',
        }[key] || key);
        return () => ({ t });
    })(),
}));

describe('TranslationPanel', () => {
    let container: HTMLDivElement | null = null;
    let root: ReturnType<typeof createRoot> | null = null;

    afterEach(() => {
        act(() => root?.unmount());
        container?.remove();
        container = null;
        root = null;
    });

    it('moves the fallback notice into an accessible header tooltip', async () => {
        translateMock.mockResolvedValue({
            translated_text: 'Привет, мир',
            fallback: true,
        });
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        await act(async () => {
            root?.render(
                React.createElement(TranslationPanel, {
                    originalText: 'Hello world',
                    onClose: vi.fn(),
                })
            );
        });

        const trigger = container.querySelector<HTMLButtonElement>(
            '.translation-fallback-trigger'
        );
        const tooltip = container.querySelector<HTMLElement>(
            '.translation-fallback-tooltip'
        );

        expect(trigger?.textContent).toBe('!');
        expect(trigger?.getAttribute('aria-describedby')).toBe(tooltip?.id);
        expect(trigger?.getAttribute('aria-expanded')).toBe('false');
        expect(tooltip?.getAttribute('role')).toBe('tooltip');
        expect(tooltip?.textContent).toBe('Translated using a fallback service');
        expect(container.querySelector('.translation-fallback-notice')).toBeNull();
        expect(container.querySelector('.translated-text')?.textContent).toContain('Привет, мир');

        act(() => trigger?.dispatchEvent(new MouseEvent('click', { bubbles: true })));
        expect(trigger?.getAttribute('aria-expanded')).toBe('true');
        expect(container.querySelector('.translation-fallback-info')?.classList).toContain('is-open');
    });
});
