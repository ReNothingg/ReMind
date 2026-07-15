import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import ThinkBlock from './ThinkBlock';
import { mergeThinkWidgets } from './thinkBlockUtils';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, options?: { value?: string | number; time?: string }) => ({
            'think.collapse': 'Collapse thoughts',
            'think.expand': 'Expand thoughts',
            'think.label': 'Thoughts',
            'think.loading': 'Thinking…',
            'think.completedLabel': `Thought for ${options?.time}`,
            'think.timeMilliseconds': `${options?.value}ms`,
            'think.timeSeconds': `${options?.value}s`,
            'webSearch.queryLabel': 'Query',
            'webSearch.sourceFallback': 'Source',
            'webSearch.sourcesAria': 'Web search sources',
            'webSearch.status.done': 'Sources found.',
            'webSearch.status.failed': 'Search failed.',
            'webSearch.status.fetching': 'Opening and reading sources…',
            'webSearch.status.noResults': 'No sources found.',
            'webSearch.status.started': 'Searching the web…',
        }[key] || key),
    }),
}));

const encodeSearchActivity = (payload: unknown) => {
    const bytes = new TextEncoder().encode(JSON.stringify(payload));
    const binary = Array.from(bytes, (byte) => String.fromCharCode(byte)).join('');
    return `<search_activity data-b64="${btoa(binary)}"></search_activity>`;
};

describe('ThinkBlock', () => {
    let container: HTMLDivElement | null = null;
    let root: Root | null = null;

    afterEach(() => {
        if (root) {
            act(() => root?.unmount());
        }
        container?.remove();
        container = null;
        root = null;
        vi.useRealTimers();
    });

    it('replaces the loading label with the streamed bold heading', () => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(ThinkBlock, {
                content: '**Initiating Russian Language**\nPreparing the response.',
                openTime: 100,
                isStreaming: true,
            }));
        });

        expect(container.querySelector('.think-block-label')?.textContent)
            .toBe('Initiating Russian Language');
    });

    it('toggles from any point of the full header and renders a timeline', () => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(ThinkBlock, {
                content: '**First step**\nDetails.\n\n**Second step**\nMore details.',
                openTime: 100,
                closeTime: 674,
            }));
        });

        const header = container.querySelector<HTMLButtonElement>('.think-block-header');
        expect(header?.getAttribute('aria-expanded')).toBe('false');
        expect(container.querySelector('.think-block-disclosure')?.getAttribute('aria-hidden')).toBe('true');

        act(() => header?.click());

        expect(header?.getAttribute('aria-expanded')).toBe('true');
        expect(container.querySelector('.think-block-wrapper')?.classList.contains('is-expanded')).toBe(true);
        expect(container.querySelector('.think-block-disclosure')?.getAttribute('aria-hidden')).toBe('false');
        expect(container.querySelectorAll('.think-block-step')).toHaveLength(2);
        expect(Array.from(container.querySelectorAll('.think-block-step-title')).map((node) => node.textContent))
            .toEqual(['Second step']);
        expect(container.querySelector('.think-block-label')?.textContent).toBe('Thought for 574ms');
        expect(container.querySelector('.think-block-timer')).toBeNull();
    });

    it('keeps the loading state in the disclosure design before content arrives', () => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(ThinkBlock, {
                content: '',
                openTime: Date.now(),
                isStreaming: true,
            }));
        });

        expect(container.querySelector('.think-block-label')?.textContent).toBe('Thinking…');
        expect(container.querySelector('.think-block-header')?.getAttribute('aria-disabled')).toBe('true');
        expect(container.querySelector('.thinking-status-dot')).toBeNull();
    });

    it('renders the complete web-search sequence with query and source results', () => {
        const started = encodeSearchActivity({
            type: 'web_search',
            status: 'web_search_started',
            query: 'latest AI news',
            sources: [],
        });
        const done = encodeSearchActivity({
            type: 'web_search',
            status: 'web_search_done',
            query: 'latest AI news',
            sources: [
                {
                    rank: 1,
                    title: 'Verified report',
                    url: 'https://example.com/report',
                    site_name: 'example.com',
                    snippet: 'A directly supported result.',
                },
                {
                    rank: 2,
                    title: '<img src=x onerror=alert(1)>',
                    url: 'javascript:alert(1)',
                    site_name: 'unsafe.example',
                    snippet: 'Still rendered safely as text.',
                },
            ],
        });

        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);
        act(() => {
            root?.render(React.createElement(ThinkBlock, {
                content: `**Planning**\nUnderstanding the request.\n\n${started}\n\n${done}\n\n**Writing**\nPreparing the answer.`,
                openTime: 100,
                closeTime: 200,
            }));
        });
        act(() => container?.querySelector<HTMLButtonElement>('.think-block-header')?.click());

        expect(container.querySelectorAll('.think-block-step')).toHaveLength(3);
        expect(container.querySelector('.think-block-label')?.textContent).toBe('Thought for 100ms');
        expect(container.textContent).toContain('latest AI news');
        expect(container.textContent).toContain('Verified report');
        expect(container.textContent).toContain('A directly supported result.');
        expect(container.querySelector('.think-block-sources-panel.is-inline')).not.toBeNull();
        expect(container.querySelector('.web-sources-count')).toBeNull();
        expect(container.querySelectorAll('.source-pill')).toHaveLength(2);
        expect(container.querySelectorAll('.think-block-step.is-search .think-block-step-marker svg'))
            .toHaveLength(1);
        expect(Array.from(container.querySelectorAll('.think-block-step-title')).map((node) => node.textContent))
            .toContain('latest AI news');
        expect(Array.from(container.querySelectorAll('.think-block-step-title')).map((node) => node.textContent))
            .not.toContain('Sources found.');
        expect(container.querySelector<HTMLAnchorElement>('a.source-pill')?.href)
            .toBe('https://example.com/report');
        expect(Array.from(container.querySelectorAll('a.source-pill')))
            .toHaveLength(1);
        expect(container.querySelector('.source-pill-name img')).toBeNull();
        expect(container.textContent).toContain('<img src=x onerror=alert(1)>');
    });

    it('shows one query-only step while a legacy search is still in progress', () => {
        const started = encodeSearchActivity({
            type: 'web_search',
            status: 'web_search_started',
            query: 'Telegram Bot API expandable blockquote',
            sources: [],
        });
        const fetching = encodeSearchActivity({
            type: 'web_search',
            status: 'web_search_fetching',
            query: 'Telegram Bot API expandable blockquote',
            sources: [],
        });

        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);
        act(() => {
            root?.render(React.createElement(ThinkBlock, {
                content: `${started}\n\n${fetching}`,
                openTime: 100,
                isStreaming: true,
            }));
        });
        act(() => container?.querySelector<HTMLButtonElement>('.think-block-header')?.click());

        const titles = Array.from(container.querySelectorAll('.think-block-step-title'))
            .map((node) => node.textContent);
        expect(container.querySelectorAll('.think-block-step.is-search')).toHaveLength(1);
        expect(titles).toEqual(['Telegram Bot API expandable blockquote']);
        expect(container.textContent).not.toContain('Searching the web');
        expect(container.textContent).not.toContain('Opening and reading sources');
        expect(container.textContent).not.toContain('Query:');
    });

    it('uses the latest search query as the collapsed label', () => {
        const firstSearch = encodeSearchActivity({
            type: 'web_search',
            status: 'web_search_done',
            query: 'first search query',
            sources: [],
        });
        const currentSearch = encodeSearchActivity({
            type: 'web_search',
            status: 'web_search_started',
            query: 'current search query',
            sources: [],
        });

        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);
        act(() => {
            root?.render(React.createElement(ThinkBlock, {
                content: `**Assessing User Frustration**\nDetails.\n\n${firstSearch}\n\n${currentSearch}`,
                openTime: 100,
                isStreaming: true,
            }));
        });

        expect(container.querySelector('.think-block-label')?.textContent)
            .toBe('current search query');
    });
});

describe('mergeThinkWidgets', () => {
    it('combines tool-round thoughts into one continuous disclosure', () => {
        const widgets = mergeThinkWidgets([
            { type: 'think', id: 'first', content: '**Gathering Facts**\nFirst.', openTime: 100, closeTime: 894 },
            { type: 'quiz', id: 'quiz' },
            { type: 'think', id: 'second', content: '**Selecting Facts**\nSecond.', openTime: 900, closeTime: 941 },
        ], 'merged');

        expect(widgets).toHaveLength(2);
        expect(widgets[0]).toMatchObject({
            type: 'think',
            id: 'merged',
            content: '**Gathering Facts**\nFirst.\n\n**Selecting Facts**\nSecond.',
            openTime: 100,
            closeTime: 941,
        });
        expect(widgets[1]).toMatchObject({ type: 'quiz', id: 'quiz' });
    });
});
