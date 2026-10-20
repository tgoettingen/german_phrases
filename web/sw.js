// Offline support: serve the app from the cache, and refresh the cache in the background,
// so an updated version is used from the next start on.
const CACHE = "german-phrases-web"; // not the phone app's cache, both may run on one origin
const FILES = ["./", "index.html", "styles.css", "app.js", "logic.js", "phrases.json",
  "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET" || new URL(request.url).origin !== location.origin) return;
  event.respondWith(caches.open(CACHE).then(async (cache) => {
    const cached = await cache.match(request, { ignoreSearch: true });
    const fresh = fetch(request).then((response) => {
      if (response.ok) cache.put(request, response.clone());
      return response;
    });
    if (cached) {
      event.waitUntil(fresh.catch(() => {})); // offline: keep using the cached copy
      return cached;
    }
    return fresh;
  }));
});
