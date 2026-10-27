/* Static-shell-only cache. Never cache clinical API responses or medical records. */
const CACHE_NAME = 'clinic-shell-v1';
const SHELL = ['/', '/index.html', '/app.css', '/app.js', '/manifest.webmanifest'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;
  if (['/', '/index.html', '/app.css', '/app.js', '/manifest.webmanifest'].includes(url.pathname)) {
    event.respondWith(fetch(event.request).then(response => {
      const copy = response.clone(); caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy)); return response;
    }).catch(() => caches.match(event.request)));
  }
});
self.addEventListener('push', event => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch { payload = {body: event.data?.text() || ''}; }
  const title = payload.title || 'Контур';
  const options = {body: payload.body || 'Новое уведомление', icon: '/icon.svg', badge: '/icon.svg', data: payload.data || {}, tag: 'clinic-notification'};
  event.waitUntil(self.registration.showNotification(title, options));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({type:'window', includeUncontrolled:true}).then(windows => {
    for (const client of windows) { if ('focus' in client) return client.focus(); }
    return self.clients.openWindow('/');
  }));
});
