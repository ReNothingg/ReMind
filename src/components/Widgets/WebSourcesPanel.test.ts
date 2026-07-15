import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import WebSourcesPanel from './WebSourcesPanel';
import { extractCompletedSearchSources } from './searchActivityUtils';
import { normalizeAndMergeWebSources } from './webSources';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string) => ({
            'webSearch.sourceFallback': 'Source',
            'webSearch.sourcesAria': 'Web search sources',
            'webSearch.sourcesLabel': 'Sources',
        }[key] || key),
    }),
}));

describe('WebSourcesPanel', () => {
    let container: HTMLDivElement | null = null;
    let root: ReturnType<typeof createRoot> | null = null;

    afterEach(() => {
        act(() => root?.unmount());
        container?.remove();
        container = null;
        root = null;
    });

    it('shows the complete aggregated source count instead of the per-search limit', () => {
        const sources = Array.from({ length: 23 }, (_, index) => ({
            title: `Page ${index + 1}`,
            site_name: `site-${index + 1}.example`,
            url: `https://site-${index + 1}.example/page`,
        }));
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => root?.render(React.createElement(WebSourcesPanel, { sources })));

        expect(container.querySelector('.web-sources-count')?.textContent).toBe('23');
        expect(container.querySelectorAll('.source-pill')).toHaveLength(23);
    });

    it('reconstructs all unique sources from legacy saved search activities', () => {
        const encodeActivity = (query: string, offset: number) => {
            const payload = {
                type: 'web_search',
                status: 'web_search_done',
                query,
                sources: Array.from({ length: 10 }, (_, index) => ({
                    rank: index + 1,
                    title: `Page ${offset + index}`,
                    site_name: `site-${offset + index}.example`,
                    url: `https://site-${offset + index}.example/page`,
                })),
            };
            const bytes = new TextEncoder().encode(JSON.stringify(payload));
            const binary = Array.from(bytes, (byte) => String.fromCharCode(byte)).join('');
            return `&lt;search_activity data-b64=&quot;${btoa(binary)}&quot;&gt;&lt;/search_activity&gt;`;
        };
        const thoughtContent = [
            encodeActivity('first query', 0),
            encodeActivity('second query', 10),
            encodeActivity('third query', 20),
            encodeActivity('fourth query', 30),
        ].join('\n');
        const extracted = extractCompletedSearchSources(thoughtContent);
        const persistedLastSearch = extracted.slice(-10);
        const merged = normalizeAndMergeWebSources(
            [extracted, persistedLastSearch],
            'Source',
        );

        expect(extracted).toHaveLength(40);
        expect(merged).toHaveLength(40);
        expect(new Set(merged.map((source) => source.url)).size).toBe(40);
    });
});
