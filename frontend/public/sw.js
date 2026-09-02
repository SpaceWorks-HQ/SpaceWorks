const CACHE_NAME = "spaceworks-static-v1";
const STATIC_DESTINATIONS = new Set(["script", "style", "image", "font"]);

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)),
    )),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  const bypass = request.method !== "GET"
    || request.mode === "navigate"
    || url.origin !== self.location.origin
    || url.pathname.startsWith("/api/")
    || url.pathname.startsWith("/api/v1/")
    || request.headers.has("Authorization")
    || !STATIC_DESTINATIONS.has(request.destination);
  if (bypass) return;

  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const cached = await cache.match(request);
      if (cached) return cached;
      const response = await fetch(request);
      if (response.ok && response.type === "basic") await cache.put(request, response.clone());
      return response;
    }),
  );
});
