import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Visualization from './Visualization';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../../context/SettingsContext', () => ({
    useSettings: () => ({
        settings: {
            theme: 'light',
            interface_language: 'en',
            accentColor: 'blue',
        },
    }),
}));

describe('Visualization', () => {
    let container: HTMLDivElement | null = null;
    let root: Root | null = null;

    afterEach(() => {
        if (root) act(() => root?.unmount());
        container?.remove();
        container = null;
        root = null;
    });

    it('renders the fragment through a script-only opaque-origin host iframe', () => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(Visualization, {
                initialState: {
                    html: '<button type="button">Run</button>',
                    title: 'Safe lab',
                    mode: 'wide',
                },
            }));
        });

        const frame = container.querySelector('iframe');
        expect(frame?.getAttribute('sandbox')).toBe('allow-scripts');
        expect(frame?.getAttribute('sandbox')).not.toContain('allow-same-origin');
        expect(frame?.getAttribute('src')).toBe('/visualization-host.html');
        expect(container.querySelector('.visualization-instance')?.classList.contains('is-wide')).toBe(true);
    });

    it('requires host confirmation before sending a follow-up message', () => {
        const onFollowUp = vi.fn();
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(Visualization, {
                initialState: { html: '<button type="button">Explore</button>' },
                onFollowUp,
            }));
        });

        const frame = container.querySelector('iframe');
        const postMessage = frame?.contentWindow
            ? vi.spyOn(frame.contentWindow, 'postMessage')
            : null;
        act(() => frame?.dispatchEvent(new Event('load')));
        const renderMessage = postMessage?.mock.calls.find(([message]) => (
            message?.type === 'remind:visualization:render'
        ))?.[0];
        const channelId = renderMessage?.channelId;
        expect(channelId).toBeTruthy();
        expect(renderMessage?.documentSource).toContain('<button type="button">Explore</button>');

        act(() => {
            window.dispatchEvent(new MessageEvent('message', {
                source: frame?.contentWindow || null,
                data: {
                    type: 'remind:visualization:follow-up',
                    channelId,
                    prompt: 'Explain the selected value',
                    title: 'Explore selection',
                },
            }));
        });

        expect(onFollowUp).not.toHaveBeenCalled();
        expect(container.querySelector('[role="dialog"]')).not.toBeNull();
        const buttons = container.querySelectorAll<HTMLButtonElement>('.visualization-follow-up-actions button');
        act(() => buttons[1]?.click());
        expect(onFollowUp).toHaveBeenCalledWith('Explain the selected value');
    });

    it('renders requested dynamic math in the host and returns it to the sandbox', () => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(Visualization, {
                initialState: { html: '<span id="formula"></span>' },
            }));
        });

        const frame = container.querySelector('iframe');
        const postMessage = frame?.contentWindow
            ? vi.spyOn(frame.contentWindow, 'postMessage')
            : null;
        act(() => frame?.dispatchEvent(new Event('load')));
        const renderMessage = postMessage?.mock.calls.find(([message]) => (
            message?.type === 'remind:visualization:render'
        ))?.[0];

        act(() => {
            window.dispatchEvent(new MessageEvent('message', {
                source: frame?.contentWindow || null,
                data: {
                    type: 'remind:visualization:math-request',
                    channelId: renderMessage?.channelId,
                    requestId: 'math-1',
                    expression: 'F=-kx',
                    displayMode: false,
                },
            }));
        });

        const result = postMessage?.mock.calls.find(([message]) => (
            message?.type === 'remind:visualization:math-result'
        ))?.[0];
        expect(result?.requestId).toBe('math-1');
        expect(result?.html).toContain('class="katex"');
        expect(result?.html).toContain('F');
    });
});
