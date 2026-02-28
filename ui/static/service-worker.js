const CACHE_NAME = 'gridbear-v2';
const STATIC_ASSETS = [
  '/static/favicon.png',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  'https://cdn.jsdelivr.net/npm/geist@1.2.0/dist/fonts/geist-sans/style.css',
  'https://cdn.jsdelivr.net/npm/geist@1.2.0/dist/fonts/geist-mono/style.css',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Only intercept static assets — skip HTML pages, API calls, SSE streams
  var url = event.request.url;
  if (event.request.mode === 'navigate' || url.indexOf('/notifications/') !== -1 || url.indexOf('/api/') !== -1) {
    return;
  }
  if (!url.match(/\.(css|js|png|woff2?|ico|svg|webmanifest)(\?|$)/)) {
    return;
  }
  event.respondWith(
    caches.match(event.request).then(function(cached) {
      if (cached) return cached;
      return fetch(event.request).then(function(response) {
        if (response.ok) {
          var clone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) { cache.put(event.request, clone); });
        }
        return response;
      });
    })
  );
});
