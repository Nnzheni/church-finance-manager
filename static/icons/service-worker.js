const CACHE_NAME    = 'afm-finance-v1';
const PRECACHE_URLS = [
  '/',                             // app shell (login)
  '/dashboard',                    // dashboard route
  '/static/css/bootstrap.min.css', // if you self-host Bootstrap
  '/static/js/bootstrap.bundle.min.js',
  '/static/js/chart.min.js',
  '/static/images/logo.png',
  // add any other static assets you need offline
];

// 1. Pre-cache on install
self.addEventListener('install', event => {
  console.log('SW: Install');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// 2. Activate and clean up old caches
self.addEventListener('activate', event => {
  console.log('SW: Activate');
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      )
    )
    .then(() => self.clients.claim())
  );
});

// 3. Intercept fetches, serve from cache first
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  
  event.respondWith(
    caches.match(event.request)
      .then(cached => {
        if (cached) return cached;
        return fetch(event.request).then(response => {
          // update cache for future
          return caches.open(CACHE_NAME).then(cache => {
            if (event.request.url.startsWith(self.location.origin)) {
              cache.put(event.request, response.clone());
            }
            return response;
          });
        });
      })
      .catch(() => {
        // optional offline fallbacks
      })
  );
});
