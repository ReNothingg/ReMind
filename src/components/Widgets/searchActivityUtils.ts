import type { RawWebSource } from './webSources';

export type SearchActivityStatus =
    | 'web_search_started'
    | 'web_search_fetching'
    | 'web_search_done'
    | 'web_search_no_results'
    | 'web_search_failed';

export type SearchActivitySource = Record<string, unknown> & {
    rank?: number;
    title: string;
    url?: string;
    displayUrl: string;
    siteName: string;
    snippet: string;
    faviconUrl: string;
};

export type DecodedSearchActivity = {
    status: SearchActivityStatus;
    query: string;
    sources: SearchActivitySource[];
};

const SEARCH_ACTIVITY_PATTERN = /<search_activity\s+data-b64="([A-Za-z0-9_+/=-]+)"\s*><\/search_activity>/g;
const VALID_SEARCH_STATUSES = new Set<SearchActivityStatus>([
    'web_search_started',
    'web_search_fetching',
    'web_search_done',
    'web_search_no_results',
    'web_search_failed',
]);
const MAX_ENCODED_ACTIVITY_LENGTH = 32_768;
const MAX_SOURCES_PER_ACTIVITY = 10;
export const MAX_EXTRACTED_SEARCH_SOURCES = 80;

export function decodeThoughtEntities(value: string): string {
    return value
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#x27;|&#39;/g, "'")
        .replace(/&amp;/g, '&');
}

function safeHttpUrl(value: unknown): string | undefined {
    try {
        const parsed = new URL(String(value || ''));
        return parsed.protocol === 'http:' || parsed.protocol === 'https:'
            ? parsed.toString()
            : undefined;
    } catch {
        return undefined;
    }
}

export function decodeSearchActivity(encoded: string): DecodedSearchActivity | null {
    if (!encoded || encoded.length > MAX_ENCODED_ACTIVITY_LENGTH) {
        return null;
    }

    try {
        const normalized = encoded.replace(/-/g, '+').replace(/_/g, '/');
        const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
        const binary = window.atob(padded);
        const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
        const payload = JSON.parse(new TextDecoder().decode(bytes));
        if (
            payload?.type !== 'web_search'
            || !VALID_SEARCH_STATUSES.has(payload.status as SearchActivityStatus)
        ) {
            return null;
        }

        const sources = Array.isArray(payload.sources)
            ? payload.sources
                .slice(0, MAX_SOURCES_PER_ACTIVITY)
                .filter((source: unknown): source is Record<string, unknown> => (
                    Boolean(source) && typeof source === 'object'
                ))
                .map((source): SearchActivitySource => ({
                    rank: Number.isFinite(Number(source.rank)) ? Number(source.rank) : undefined,
                    title: String(source.title || '').slice(0, 240),
                    url: safeHttpUrl(source.url),
                    displayUrl: String(source.display_url || source.displayUrl || '').slice(0, 240),
                    siteName: String(source.site_name || source.siteName || '').slice(0, 160),
                    snippet: String(source.snippet || '').slice(0, 600),
                    faviconUrl: safeHttpUrl(source.favicon_url || source.faviconUrl) || '',
                }))
            : [];

        return {
            status: payload.status,
            query: String(payload.query || '').slice(0, 500),
            sources,
        };
    } catch {
        return null;
    }
}

export function extractCompletedSearchSources(
    value: string,
    maxSources = MAX_EXTRACTED_SEARCH_SOURCES,
): RawWebSource[] {
    const text = decodeThoughtEntities(String(value || ''));
    const sources: RawWebSource[] = [];
    let match: RegExpExecArray | null;
    SEARCH_ACTIVITY_PATTERN.lastIndex = 0;

    while (sources.length < maxSources && (match = SEARCH_ACTIVITY_PATTERN.exec(text)) !== null) {
        const activity = decodeSearchActivity(match[1]);
        if (activity?.status !== 'web_search_done') {
            continue;
        }
        sources.push(...activity.sources.slice(0, maxSources - sources.length));
    }

    return sources;
}
