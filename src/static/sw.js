const CACHE_NAME = 'ci-dashboard-v3';
const STATIC_ASSETS = [
    '/',
    '/static/index.html',
    '/static/design-system.css',
    '/manifest.json',
    '/static/img/icon-192.png',
    '/static/img/icon-512.png',
    '/static/img/maskable-icon.png'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches['open'](CACHE_NAME).then(cache => {
            return cache.addAll(STATIC_ASSETS);
        })
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheName !== CACHE_NAME) {
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
});

self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);
    if (url.pathname.startsWith('/api/')) {
        // Network First for APIs
        event.respondWith(
            self['fetch'](event.request).catch(() => {
                return caches.match(event.request);
            })
        );
    } else {
        // Cache First for static assets
        event.respondWith(
            caches.match(event.request).then(response => {
                return response || self['fetch'](event.request);
            })
        );
    }
});
