const TERMINAL_WEB_SEARCH_STATUSES = new Set([
    'web_search_done',
    'web_search_no_results',
    'web_search_failed',
    'web_search_skipped',
    'generating_text',
]);

export function isActiveWebSearchStatus(status: unknown): boolean {
    const value = String(status || '');
    return value.startsWith('web_search_') && !TERMINAL_WEB_SEARCH_STATUSES.has(value);
}
