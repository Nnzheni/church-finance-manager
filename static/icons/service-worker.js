const CACHE_NAME    = 'afm-finance-v1';
const PRECACHE_URLS = [
  '/',                             // the app shell (login redirects here)
  '/dashboard',                    // your main SPA route
  '/static/index.html',            // if you have standalone HTML shells
  '/static/css/bootstrap.min.css', // bootstrap
  '/static/js/bootstrap.bundle.min.js',
  '/static/js/chart.min.js',
  '/static/images/logo.png',       // your church logo
  // ...add any other static assets you know you'll need offline:
];

// 1. Pre‐cache on install
self.addEventListener('install', event => {
  console.log('Service Worker: Install');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// 2. Activate and clean up old caches
self.addEventListener('activate', event => {
  console.log('Service Worker: Activate');
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
  // only handle GET requests
  if (event.request.method !== 'GET') return;
  
  event.respondWith(
    caches.match(event.request)
      .then(cached => {
        if (cached) return cached;         // cache hit
        return fetch(event.request)        // else go to network
          .then(response => {
            // optionally update cache for future visits
            return caches.open(CACHE_NAME).then(cache => {
              // only cache same‐origin requests
              if (event.request.url.startsWith(self.location.origin)) {
                cache.put(event.request, response.clone());
              }
              return response;
            });
          });
      })
      .catch(() => {
        // offline fallback (optional)
        // return caches.match('/static/offline.html');
      })
  );
});
