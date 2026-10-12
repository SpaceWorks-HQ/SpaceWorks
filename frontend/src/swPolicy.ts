export function kioskNavigation(path: string) {
  return /^\/kiosk\/[^/]+\/?$/.test(path) || /^\/m\/[^/]+\/kiosk\/[^/]+\/?$/.test(path);
}

export function cachePolicy(request: Pick<Request, "url" | "method" | "mode" | "headers">,
  origin: string, precachePaths: Set<string>) {
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== origin || url.pathname.startsWith("/api/")
      || request.headers.has("Authorization")) return "network";
  if (request.mode === "navigate") return kioskNavigation(url.pathname) ? "kiosk" : "network";
  // Only build-manifest URLs qualify, never runtime images/evidence or config.
  return !url.search && precachePaths.has(url.pathname) ? "static" : "network";
}
