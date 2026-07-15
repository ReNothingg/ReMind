import { describe, expect, it } from 'vitest';

import { isActiveWebSearchStatus } from './webSearchStatus';

describe('isActiveWebSearchStatus', () => {
    it('keeps only in-progress search statuses visible', () => {
        expect(isActiveWebSearchStatus('web_search_querying')).toBe(true);
        expect(isActiveWebSearchStatus('web_search_started')).toBe(true);
        expect(isActiveWebSearchStatus('web_search_fetching')).toBe(true);
        expect(isActiveWebSearchStatus('web_search_done')).toBe(false);
        expect(isActiveWebSearchStatus('web_search_failed')).toBe(false);
        expect(isActiveWebSearchStatus('generating_text')).toBe(false);
    });
});
