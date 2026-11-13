const CACHE_NAME = 'ci-dashboard-v10';
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
        event.request.method !== 'GET' ||
        url.pathname.startsWith('/oauth') ||
        url.pathname.startsWith('/mcp') ||
        url.pathname.startsWith('/.well-known')
    ) {
        return;
    }

    if (
        url.pathname.startsWith('/api/') ||
        url.pathname.startsWith('/configure')
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
        // Network First with Cache Update and Fallback for static assets
        event.respondWith(
            self['fetch'](event.request).then(response => {
                if (response && response.status === 200 && event.request.method === 'GET') {
                    const responseClone = response.clone();
                    self['caches']['open'](CACHE_NAME).then(cache => {
                        cache.put(event.request, responseClone);
                    });
                }
                return response;
            }).catch(() => {
                return self['caches']['match'](event.request).then(cached => {
                    return cached || new Response('Offline or asset unavailable', {
                        status: 503,
                        statusText: 'Service Unavailable',
                        headers: { 'Content-Type': 'text/plain' }
                    });
                });
            })
        );
    }
});
