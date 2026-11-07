const CACHE_NAME = 'ci-dashboard-v8';
const STATIC_ASSETS = [
    '/',
    '/static/design-system.css',
    '/static/oauth-notify.js',
    '/manifest.json',
    '/static/img/icon-192.png',
    '/static/img/icon-512.png',
    '/static/img/maskable-icon.png'
];

self.addEventListener('install', event => {
    self.skipWaiting();
    event.waitUntil(
        self['caches']['open'](CACHE_NAME).then(cache => {
            return cache.addAll(STATIC_ASSETS);
        })
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        self['caches']['keys']().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheName !== CACHE_NAME) {
                        return self['caches']['delete'](cacheName);
                    }
                    return Promise.resolve();
                })
            );
        }).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);
    if (url.origin !== self.location.origin) {
        return;
    }

    if (
        url.pathname.startsWith('/api/') ||
        url.pathname.startsWith('/oauth') ||
        url.pathname.startsWith('/configure') ||
        url.pathname.startsWith('/.well-known')
    ) {
        // Network First for APIs and OAuth endpoints, with valid Response fallback
        event.respondWith(
            self['fetch'](event.request).catch(() => {
                return self['caches']['match'](event.request).then(cached => {
                    return cached || new Response(
                        JSON.stringify({ error: 'Network error or server unreachable' }),
                        {
                            status: 503,
                            statusText: 'Service Unavailable',
                            headers: { 'Content-Type': 'application/json' }
                        }
                    );
                });
            })
        );
    } else {
        // Cache First for static assets, with valid Response fallback
        event.respondWith(
            self['caches']['match'](event.request).then(response => {
                if (response) {
                    return response;
                }
                return self['fetch'](event.request).catch(() => {
                    return new Response('Offline or asset unavailable', {
                        status: 503,
                        statusText: 'Service Unavailable',
                        headers: { 'Content-Type': 'text/plain' }
                    });
                });
            })
        );
    }
});
