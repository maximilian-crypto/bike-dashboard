// Service Worker: macht die App installierbar + offline-fähig.
// Strategie: NETWORK-FIRST für die App-Hülle (immer die aktuelle Version laden,
// nur ohne Netz aus dem Cache) – so gibt es keine veraltete ride.html.
const CACHE = 'ride-v3';

self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim())
));
self.addEventListener('fetch', e => {
  const url = e.request.url;
  // Live-Daten (Kartenkacheln, Wetter, Routing) immer frisch aus dem Netz.
  if (url.includes('tile.openstreetmap') || url.includes('open-meteo') ||
      url.includes('openrouteservice')) return;
  // Leaflet ist versioniert und unveränderlich → CACHE-FIRST. Vorher kam es bei
  // jedem Start neu aus dem Netz; ohne Empfang fehlte es, L war undefiniert und
  // die App startete nicht sauber durch.
  if (url.includes('unpkg')) {
    e.respondWith(
      caches.match(e.request).then(hit => hit || fetch(e.request).then(resp => {
        const c = resp.clone();
        caches.open(CACHE).then(ca => ca.put(e.request, c));
        return resp;
      }))
    );
    return;
  }
  // App-Hülle: erst Netz, dann Cache (offline-Fallback).
  e.respondWith(
    fetch(e.request)
      .then(resp => { const c = resp.clone(); caches.open(CACHE).then(ca => ca.put(e.request, c)); return resp; })
      .catch(() => caches.match(e.request))
  );
});
