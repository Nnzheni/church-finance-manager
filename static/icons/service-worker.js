self.addEventListener('install', (e) => {
  console.log('Service Worker Installed');
  e.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (e) => {
  console.log('Service Worker Activated');
  return self.clients.claim();
});
