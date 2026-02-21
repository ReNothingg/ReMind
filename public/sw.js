

const CACHE_VERSION = 'v1';
const STATIC_CACHE = `remind-static-${CACHE_VERSION}`;

const PRECACHE_URLS = [
    '/',
    '/manifest.json',
    '/icons/branding/logo-512.png',
    '/icons/branding/logo-192.png',
    '/icons/branding/logo-32.png',
    '/icons/branding/logo-16.png',
    '/icons/branding/apple-touch-icon.png',
];

const BYPASS_PREFIXES = [
    '/api',
    '/chat',
    '/uploads',
    '/sessions',
    '/login',
    '/synthesize',
    '/translate',
    '/canvas-action',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        (async () => {
            const cache = await caches.open(STATIC_CACHE);
            await cache.addAll(PRECACHE_URLS);
            await self.skipWaiting();
        })(),
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        (async () => {
            const keys = await caches.keys();
            await Promise.all(
                keys
                    .filter((k) => k.startsWith('remind-static-') && k !== STATIC_CACHE)
                    .map((k) => caches.delete(k)),
            );
            await self.clients.claim();
        })(),
    );
});

function isBypassedPath(url) {
    return BYPASS_PREFIXES.some((p) => url.pathname.startsWith(p));
}

async function networkFirst(request) {
    const cache = await caches.open(STATIC_CACHE);
    try {
        const fresh = await fetch(request);
        if (request.method === 'GET' && fresh && fresh.ok) {
            cache.put(request, fresh.clone());
        }
        return fresh;
    } catch (err) {
        const cached = await cache.match(request);
        if (cached) return cached;
        throw err;
    }
}

async function staleWhileRevalidate(request) {
    const cache = await caches.open(STATIC_CACHE);
    const cached = await cache.match(request);

    const fetchPromise = fetch(request)
        .then((response) => {
            if (request.method === 'GET' && response && response.ok) {
                cache.put(request, response.clone());
            }
            return response;
        })
        .catch(() => null);

    return cached || (await fetchPromise);
}

self.addEventListener('fetch', (event) => {
    const request = event.request;

    if (request.method !== 'GET') return;

    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    if (isBypassedPath(url)) return;
    if (request.mode === 'navigate') {
        event.respondWith(
            (async () => {
                try {
                    return await networkFirst(request);
                } catch (_err) {
                    const cache = await caches.open(STATIC_CACHE);
                    return (await cache.match('/')) || Response.error();
                }
            })(),
        );
        return;
    }
    const dest = request.destination;
    if (['script', 'style', 'image', 'font'].includes(dest)) {
        event.respondWith(staleWhileRevalidate(request));
        return;
    }
    event.respondWith(networkFirst(request));
});
