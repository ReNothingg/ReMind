export const sourceFallbackIcon = '/icons/ui/web.svg';

export type RawWebSource = string | Record<string, unknown>;

export type NormalizedWebSource = {
    rank: number;
    title: string;
    url: string;
    displayUrl: string;
    siteName: string;
    snippet: string;
    faviconUrl: string;
};

function safeHttpUrl(value: unknown): string {
    try {
        const parsed = new URL(String(value || '').trim());
        return parsed.protocol === 'http:' || parsed.protocol === 'https:'
            ? parsed.toString()
            : '';
    } catch {
        return '';
    }
}

export function normalizeWebSource(
    source: RawWebSource,
    index: number,
    sourceFallbackLabel = 'Source',
): NormalizedWebSource | null {
    const fallbackTitle = `${sourceFallbackLabel} ${index + 1}`;
    if (typeof source === 'string') {
        const url = safeHttpUrl(source);
        let siteName = fallbackTitle;
        if (url) {
            try {
                siteName = new URL(url).hostname.replace(/^www\./, '');
            } catch {
                siteName = fallbackTitle;
            }
        }
        return {
            rank: index + 1,
            title: siteName,
            url,
            displayUrl: url ? siteName : source,
            siteName,
            snippet: '',
            faviconUrl: sourceFallbackIcon,
        };
    }

    if (!source || typeof source !== 'object') {
        return null;
    }

    const url = safeHttpUrl(source.url || source.final_url || source.finalUrl);
    let siteName = String(source.site_name || source.siteName || '').trim();
    if (!siteName && url) {
        try {
            siteName = new URL(url).hostname.replace(/^www\./, '');
        } catch {
            siteName = '';
        }
    }

    const title = String(source.title || siteName || fallbackTitle).trim();
    const faviconUrl = safeHttpUrl(source.favicon_url || source.faviconUrl);
    const rank = Number(source.rank);
    return {
        rank: Number.isFinite(rank) ? rank : index + 1,
        title,
        url,
        displayUrl: String(source.display_url || source.displayUrl || siteName || url).trim(),
        siteName: siteName || title,
        snippet: String(source.snippet || '').trim(),
        faviconUrl: faviconUrl || sourceFallbackIcon,
    };
}

export function normalizeWebSources(
    sources: RawWebSource[] | undefined,
    sourceFallbackLabel = 'Source',
): NormalizedWebSource[] {
    return (Array.isArray(sources) ? sources : [])
        .map((source, index) => normalizeWebSource(source, index, sourceFallbackLabel))
        .filter((source): source is NormalizedWebSource => Boolean(source))
        .filter((source) => Boolean(source.url || source.title));
}

export function normalizeAndMergeWebSources(
    sourceGroups: Array<RawWebSource[] | undefined>,
    sourceFallbackLabel = 'Source',
    maxSources = 80,
): NormalizedWebSource[] {
    const merged: NormalizedWebSource[] = [];
    const positions = new Map<string, number>();

    sourceGroups.forEach((sources) => {
        normalizeWebSources(sources, sourceFallbackLabel).forEach((source) => {
            const identity = source.url
                ? `url:${source.url}`
                : `meta:${source.siteName.toLocaleLowerCase()}\u001f${source.title.toLocaleLowerCase()}\u001f${source.displayUrl.toLocaleLowerCase()}`;
            const existingIndex = positions.get(identity);
            if (existingIndex !== undefined) {
                const existing = merged[existingIndex];
                merged[existingIndex] = {
                    ...existing,
                    title: existing.title || source.title,
                    displayUrl: existing.displayUrl || source.displayUrl,
                    siteName: existing.siteName || source.siteName,
                    snippet: existing.snippet || source.snippet,
                    faviconUrl: existing.faviconUrl === sourceFallbackIcon
                        ? source.faviconUrl
                        : existing.faviconUrl,
                };
                return;
            }
            if (merged.length >= maxSources) {
                return;
            }
            positions.set(identity, merged.length);
            merged.push(source);
        });
    });

    return merged;
}
