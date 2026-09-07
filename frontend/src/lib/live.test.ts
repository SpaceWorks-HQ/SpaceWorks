import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { connectLiveUpdates, keyMatchesKind, parseSseChunk } from "./live";

vi.mock("./api/client", () => ({
  API_V1_URL: "http://api.test/api/v1",
  authHeaders: () => ({ Authorization: "Bearer test-token" }),
  getAccessToken: () => "test-token",
}));

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
}

describe("parseSseChunk", () => {
  it("splits complete events and keeps the partial tail", () => {
    const { events, rest } = parseSseChunk('retry: 5000\n\nevent: change\ndata: {"kind":"a"}\n\ndata: {"ki');
    expect(events).toEqual(['{"kind":"a"}']);
    expect(rest).toBe('data: {"ki');
  });
  it("ignores comments and joins multi-line data", () => {
    const { events } = parseSseChunk(": keep-alive\n\ndata: one\ndata: two\n\n");
    expect(events).toEqual(["one\ntwo"]);
  });
});

describe("keyMatchesKind", () => {
  it("maps request changes onto request, loan and inventory keys but not machines", () => {
    expect(keyMatchesKind(["pending-requests", 3], "request.accepted")).toBe(true);
    expect(keyMatchesKind(["direct-loans", 3], "request.issued")).toBe(true);
    expect(keyMatchesKind(["machines", 3], "request.issued")).toBe(false);
  });
  it("maps machine changes onto machine keys only", () => {
    expect(keyMatchesKind(["machines", 3], "machine_service.completed")).toBe(true);
    expect(keyMatchesKind(["pending-requests", 3], "machine_service.completed")).toBe(false);
  });
  it("invalidates everything for an unknown kind", () => {
    expect(keyMatchesKind(["anything"], "totally.new")).toBe(true);
  });
});

describe("connectLiveUpdates", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("invalidates matching queries once per burst and sends the bearer token", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();
    const fetchImpl = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer test-token");
      return new Response(
        streamOf([
          'retry: 5000\n\nevent: change\ndata: {"kind":"request.accepted","makerspace_id":1,"target_type":"hardware_requests.hardwarerequest","target_id":"9","actor_id":2,"ts":"t"}\n\n',
          'event: change\ndata: {"kind":"request.issued","makerspace_id":1,"target_type":"x","target_id":"9","actor_id":2,"ts":"t"}\n\n',
        ]),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      );
    });
    const stop = connectLiveUpdates(queryClient, { fetchImpl: fetchImpl as typeof fetch, debounceMs: 50, maxBackoffMs: 1000 });
    await vi.advanceTimersByTimeAsync(10);
    await vi.advanceTimersByTimeAsync(100);
    expect(invalidate).toHaveBeenCalledTimes(1);
    const predicate = (invalidate.mock.calls[0][0] as unknown as { predicate: (q: { queryKey: unknown[] }) => boolean }).predicate;
    expect(predicate({ queryKey: ["pending-requests", 1] })).toBe(true);
    expect(predicate({ queryKey: ["machines", 1] })).toBe(false);
    stop();
  });

  it("stops without retrying on 401 or 503", async () => {
    const queryClient = new QueryClient();
    const fetchImpl = vi.fn(async () => new Response("", { status: 503 }));
    const stop = connectLiveUpdates(queryClient, { fetchImpl: fetchImpl as unknown as typeof fetch });
    await vi.advanceTimersByTimeAsync(10);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    stop();
  });

  it("reconnects with backoff after a dropped stream", async () => {
    const queryClient = new QueryClient();
    vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();
    const fetchImpl = vi.fn(async () => new Response(streamOf(["retry: 5000\n\n"]), { status: 200 }));
    const stop = connectLiveUpdates(queryClient, { fetchImpl: fetchImpl as unknown as typeof fetch, maxBackoffMs: 4000 });
    await vi.advanceTimersByTimeAsync(10);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1100);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(2100);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    stop();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });
});
