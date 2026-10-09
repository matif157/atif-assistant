const CACHE = "atif-assistant-v4";
// Shell only. App JS/CSS must never be served stale, or fixes appear not to
// work. The index is network-first so updates land immediately.
const SHELL = ["/", "/static/style.css", "/static/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// App shell only. Never cache /api/* - answers must be live.
// Strategy: network-first for code, cache fallback so the UI opens offline.
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return;

  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok && (url.pathname === "/" || url.pathname.startsWith("/static/"))) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
