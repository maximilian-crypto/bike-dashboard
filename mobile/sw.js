// Service Worker: macht die App installierbar + offline-fähig.
// Strategie: NETWORK-FIRST für die App-Hülle (immer die aktuelle Version laden,
// nur ohne Netz aus dem Cache) – so gibt es keine veraltete ride.html.
const CACHE = 'ride-v2';

self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim())
));
self.addEventListener('fetch', e => {
  const url = e.request.url;
  // Externe Ressourcen (Karte, Wetter, Leaflet) immer direkt aus dem Netz.
  if (url.includes('tile.openstreetmap') || url.includes('open-meteo') ||
      url.includes('unpkg') || url.includes('openrouteservice')) return;
  // App-Hülle: erst Netz, dann Cache (offline-Fallback).
  e.respondWith(
    fetch(e.request)
      .then(resp => { const c = resp.clone(); caches.open(CACHE).then(ca => ca.put(e.request, c)); return resp; })
      .catch(() => caches.match(e.request))
  );
});
