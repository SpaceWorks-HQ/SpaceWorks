// Live-update client for /api/v1/live/ (Server-Sent Events).
//
// The stream carries hints, not data: `{kind, makerspace_id, target_type, target_id, ...}`
// for every committed state change the session is allowed to hear about. On a hint we
// invalidate the TanStack queries whose keys plausibly cover that kind of thing and let
// them refetch through the ordinary, RBAC-scoped endpoints. Server state stays in the
// query cache; this module only tells the cache that it is stale.
//
// `EventSource` cannot send an Authorization header and staff auth is a bearer token, so the
// stream is read with `fetch` and a small SSE parser instead. Reconnects use exponential
// backoff; auth failures stop the client (the session layer handles re-login); a 503 means
// the deployment has no Redis and polling stays the only mechanism.
import type { QueryClient } from "@tanstack/react-query";

import { API_V1_URL, authHeaders, getAccessToken } from "./api/client";

export type LiveEvent = {
  kind: string;
  makerspace_id: number | null;
  target_type: string;
  target_id: string;
  actor_id: number | null;
  ts: string;
};

// Which query keys a kind of change can stale. Keys in this app are string-y
// (`["pending-requests", id]`, `["machines", ...]`), so a substring match on the
// serialised key is the pragmatic contract. Unknown kinds invalidate every active query.
const KIND_KEY_HINTS: Array<[RegExp, string[]]> = [
  [/^(request|loan|handover|return|self_checkout|direct_loan|evidence|box|qr)/, ["request", "loan", "ledger", "inventory", "dashboard", "accountab", "scanner", "evidence", "box", "qr", "queue"]],
  [/^(inventory|product|stock|asset|container|category)/, ["inventory", "product", "stock", "asset", "container", "categor", "dashboard", "ledger"]],
  [/^(machine|service|print|maintenance|consumable|warranty)/, ["machine", "service", "print", "maintenance", "consumable", "warranty", "dashboard"]],
  [/^(event|registration|checkin|series|certificate|feedback)/, ["event", "registration", "checkin", "series", "certificate", "feedback"]],
  [/^booking/, ["booking"]],
  [/^(notification|delivery)/, ["notification", "inbox", "unread"]],
  [/^(member|membership|profile|waiver|user|role|staff|invitation)/, ["member", "user", "role", "staff", "profile", "directory", "invitation", "waiver"]],
  [/^(payment|charge|refund)/, ["payment", "charge", "refund", "receipt"]],
];

export function keyMatchesKind(queryKey: readonly unknown[], kind: string): boolean {
  const flat = JSON.stringify(queryKey).toLowerCase();
  for (const [pattern, hints] of KIND_KEY_HINTS) {
    if (pattern.test(kind)) return hints.some((hint) => flat.includes(hint));
  }
  return true;
}

export function parseSseChunk(buffer: string): { events: string[]; rest: string } {
  const events: string[] = [];
  let rest = buffer;
  for (;;) {
    const boundary = rest.indexOf("\n\n");
    if (boundary < 0) break;
    const block = rest.slice(0, boundary);
    rest = rest.slice(boundary + 2);
    const data = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (data) events.push(data);
  }
  return { events, rest };
}

export type LiveOptions = {
  fetchImpl?: typeof fetch;
  debounceMs?: number;
  maxBackoffMs?: number;
  url?: string;
};

export function connectLiveUpdates(queryClient: QueryClient, options: LiveOptions = {}): () => void {
  const fetchImpl = options.fetchImpl ?? ((input, init) => fetch(input, init));
  const debounceMs = options.debounceMs ?? 300;
  const maxBackoffMs = options.maxBackoffMs ?? 30_000;
  const url = options.url ?? `${API_V1_URL}/live/`;

  let stopped = false;
  let controller: AbortController | null = null;
  let backoff = 1000;
  let pendingKinds = new Set<string>();
  let flushTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  const flush = () => {
    flushTimer = null;
    const kinds = Array.from(pendingKinds);
    pendingKinds = new Set();
    if (kinds.length === 0) return;
    void queryClient.invalidateQueries({
      predicate: (query) => kinds.some((kind) => keyMatchesKind(query.queryKey, kind)),
    });
  };

  const onEvent = (raw: string) => {
    let parsed: Partial<LiveEvent>;
    try {
      parsed = JSON.parse(raw) as Partial<LiveEvent>;
    } catch {
      return;
    }
    pendingKinds.add(typeof parsed.kind === "string" ? parsed.kind : "");
    if (!flushTimer) flushTimer = setTimeout(flush, debounceMs);
  };

  const scheduleReconnect = () => {
    if (stopped) return;
    reconnectTimer = setTimeout(() => void connect(), backoff);
    backoff = Math.min(backoff * 2, maxBackoffMs);
  };

  const connect = async () => {
    if (stopped || !getAccessToken()) return;
    controller = new AbortController();
    try {
      const response = await fetchImpl(url, {
        headers: { ...authHeaders(), Accept: "text/event-stream" },
        signal: controller.signal,
        credentials: "include",
      });
      if (response.status === 401 || response.status === 403) return; // session layer re-logins
      if (response.status === 503) return; // no live transport on this deployment
      if (!response.ok || !response.body) {
        scheduleReconnect();
        return;
      }
      const connectedAt = Date.now();
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const { events, rest } = parseSseChunk(buffer);
        buffer = rest;
        events.forEach(onEvent);
      }
      // A stream that stayed up for a while earned a fresh backoff; one that dropped at once
      // keeps doubling, so a flapping upstream is not hammered once a second.
      if (Date.now() - connectedAt >= 10_000) backoff = 1000;
      scheduleReconnect();
    } catch {
      if (!stopped) scheduleReconnect();
    }
  };

  void connect();

  return () => {
    stopped = true;
    controller?.abort();
    if (flushTimer) clearTimeout(flushTimer);
    if (reconnectTimer) clearTimeout(reconnectTimer);
  };
}
