import React, { act, createRef } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ModelSelector } from './GlobalHeader';
import type { ThinkingLevel } from '../../../services/api';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string) => ({
            'models.thinkingLevel': 'Thinking level',
            'models.thinkingLevelDescription': 'Controls reasoning depth',
            'models.thinkingLevels.minimal': 'Minimal',
            'models.thinkingLevels.low': 'Low',
            'models.thinkingLevels.medium': 'Medium',
            'models.thinkingLevels.high': 'High',
        }[key] || key),
    }),
}));

describe('ModelSelector thinking control', () => {
    let container: HTMLDivElement | null = null;
    let root: Root | null = null;

    afterEach(() => {
        act(() => root?.unmount());
        container?.remove();
        container = null;
        root = null;
    });

    it('renders all Flash-Lite levels and changes the selected level', () => {
        const onThinkingLevelChange = vi.fn();
        const model = {
            id: 'base',
            name: 'Gemini 3.1 Flash Lite',
            desc: 'Fast model',
            thinkingLevels: ['minimal', 'low', 'medium', 'high'] as ThinkingLevel[],
            defaultThinkingLevel: 'medium' as const,
        };
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(ModelSelector, {
                activeModel: model,
                currentModel: 'base',
                dropdownId: 'model-selector-test',
                dropdownRef: createRef<HTMLDivElement>(),
                isDropdownOpen: true,
                models: [model],
                onCloseDropdown: vi.fn(),
                onModelChange: vi.fn(),
                thinkingLevel: 'medium',
                onThinkingLevelChange,
                onToggleDropdown: vi.fn(),
                chooseLabel: 'Choose a model',
            }));
        });

        const slider = container.querySelector<HTMLInputElement>('.model-thinking-input');
        expect(slider?.value).toBe('2');
        expect(slider?.getAttribute('aria-valuetext')).toBe('Medium');
        expect(container.querySelector('.model-thinking-labels')).toBeNull();
        expect(slider?.closest('.model-option-card.is-selected')).not.toBeNull();
        expect(container.querySelector('.model-btn-variant')?.textContent).toBe('Medium');
        const markerPositions = Array.from(
            container.querySelectorAll<HTMLElement>('.model-thinking-marker'),
            (marker) => marker.style.left,
        );
        expect(markerPositions[0]).toBe('22px');
        expect(markerPositions[3]).toBe('calc(100% - 22px)');
        expect(container.querySelector('.model-dropdown-header')).toBeNull();
        expect(container.querySelector('.model-dropdown')?.getAttribute('aria-label')).toBe('Choose a model');

        act(() => {
            if (slider) {
                const valueSetter = Object.getOwnPropertyDescriptor(
                    HTMLInputElement.prototype,
                    'value',
                )?.set;
                valueSetter?.call(slider, '3');
                slider.dispatchEvent(new Event('input', { bubbles: true }));
                slider.dispatchEvent(new Event('change', { bubbles: true }));
            }
        });

        expect(onThinkingLevelChange).toHaveBeenCalledWith('high');
    });
});
