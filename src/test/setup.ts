import { afterEach, beforeEach, vi } from 'vitest';

function createStorageShim() {
    const store = new Map<string, string>();

    return {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => {
            store.set(key, String(value));
        },
        removeItem: (key: string) => {
            store.delete(key);
        },
        clear: () => {
            store.clear();
        },
        key: (index: number) => Array.from(store.keys())[index] ?? null,
        get length() {
            return store.size;
        },
    } as Storage;
}

function ensureStorage(name: 'localStorage' | 'sessionStorage') {
    const existing = globalThis[name];
    if (existing && typeof existing.clear === 'function') {
        return existing;
    }

    const shim = createStorageShim();
    Object.defineProperty(globalThis, name, {
        value: shim,
        configurable: true,
        writable: true,
    });
    return shim;
}

beforeEach(() => {
    ensureStorage('localStorage').clear();
    ensureStorage('sessionStorage').clear();
    document.cookie = 'csrf_token=test_csrf; path=/';
});

afterEach(() => {
    vi.restoreAllMocks();
});
