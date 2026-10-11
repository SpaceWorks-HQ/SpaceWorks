// The shell reads explicit last-known card/loan projections from local storage.
// This worker owns only member navigation. No API, authenticated response,
// runtime image, staff route, or kiosk queue enters its cache.
const MEMBER_ASSETS = ["/member-pwa/offline.html", "/member-pwa/offline.js", "/member-pwa/offline.css", "/member-pwa/icon-192.png", "/member-pwa/icon-512.png"];
const memberPath = new URL(self.registration.scope).pathname.replace(/\/$/, "");
const MEMBER_CACHE_PREFIX = "spaceworks-member-shell-" + encodeURIComponent(memberPath) + "-";
const MEMBER_CACHE = MEMBER_CACHE_PREFIX + "__MEMBER_REVISION__";
self.addEventListener("install", event => {
  event.waitUntil(caches.open(MEMBER_CACHE).then(cache => cache.addAll(MEMBER_ASSETS)));
});
self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    await Promise.all((await caches.keys()).filter(name => name.startsWith(MEMBER_CACHE_PREFIX) && name !== MEMBER_CACHE).map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || request.headers.has("Authorization")) return;
  if (url.pathname === `${memberPath}/manifest.webmanifest`) {
    const name = (url.searchParams.get("name") || "SpaceWorks member").slice(0, 100);
    event.respondWith(Promise.resolve(new Response(JSON.stringify({
      id: memberPath, name, short_name: name.slice(0, 24), start_url: memberPath, scope: memberPath,
      display: "standalone", background_color: "#1e333f", theme_color: "#1e333f",
      icons: [192, 512].map(size => ({ src: `/member-pwa/icon-${size}.png`, sizes: `${size}x${size}`, type: "image/png", purpose: "any" })),
    }), { headers: { "Content-Type": "application/manifest+json", "Cache-Control": "no-store" } })));
    return;
  }
  if (request.mode === "navigate" && (url.pathname === memberPath || url.pathname === `${memberPath}/`)) {
    event.respondWith((async () => {
      try {
        const response = await fetch(request, { signal: AbortSignal.timeout(5000) });
        if (response.status >= 500) throw new Error("Member area unavailable");
        return response;
      } catch { return await (await caches.open(MEMBER_CACHE)).match("/member-pwa/offline.html") || Response.error(); }
    })());
    return;
  }
  if (!url.search && MEMBER_ASSETS.includes(url.pathname)) {
    event.respondWith(caches.open(MEMBER_CACHE).then(async cache => await cache.match(url.pathname) || fetch(request)));
  }
});
