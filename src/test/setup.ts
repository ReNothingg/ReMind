import { afterEach, beforeEach, vi } from 'vitest';

beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    document.cookie = 'csrf_token=test_csrf; path=/';
});

afterEach(() => {
    vi.restoreAllMocks();
});
