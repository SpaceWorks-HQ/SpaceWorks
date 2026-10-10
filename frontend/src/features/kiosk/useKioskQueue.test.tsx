import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { useKioskQueue } from "./useKioskQueue";
import { listQueues, loadQueue } from "./offlineQueueStore";
import { session, lease, work, draft } from "./offlineTestFixtures";
import type { OfflineQueue } from "./offlineQueueTypes";

vi.mock("./offlineQueueStore", () => ({ listQueues: vi.fn(), loadQueue: vi.fn(), saveWorkPackage: vi.fn(), wipeQueue: vi.fn() }));
vi.mock("./kioskReplayClient", () => ({ replayQueue: vi.fn() }));
beforeEach(() => { vi.clearAllMocks(); vi.mocked(listQueues).mockResolvedValue([]); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("does not treat onLine=true as proof that a cold Station can unlock", async () => {
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
  const fetcher = vi.fn().mockRejectedValue(new TypeError("network unavailable")); vi.stubGlobal("fetch", fetcher);
  const { result } = renderHook(() => useKioskQueue("token", "space"));
  await waitFor(() => expect(fetcher).toHaveBeenCalled());
  expect(result.current.online).toBe(false);
  expect(fetcher.mock.calls[0][0]).toContain("/health/");
  expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: "omit", cache: "no-store" });
  expect(result.current.queue).toBeNull();
  fetcher.mockResolvedValue({ ok: true });
  act(() => window.dispatchEvent(new Event("online")));
  await waitFor(() => expect(result.current.online).toBe(true));
});

it("keeps a cached handover in offline mode when the reachable backend is unhealthy", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
  const { result } = renderHook(() => useKioskQueue("token"));
  await waitFor(() => expect(listQueues).toHaveBeenCalled());
  expect(result.current.online).toBe(false);
});

it("restores the explicitly selected correction without choosing between unrelated shifts", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  const queue: OfflineQueue = { version: 1, scope: "original", token: "token", apiBase: "/api/v1", session, lease,
    works: [{ id: "work", aggregateId: "aggregate", work }], commands: [{ envelope: draft(),
      workPackageId: "work", evidenceRecordId: null, status: "queued", attempts: 0, nextRetryAt: 0,
      lastFailure: null, result: null, uploaded: false }] };
  const correction: OfflineQueue = { ...queue, scope: "correction", commands: [
    { ...queue.commands[0], recoveryReplayId: "selected-failure" },
  ] };
  vi.mocked(listQueues).mockResolvedValue([queue, correction]);
  vi.mocked(loadQueue).mockResolvedValue(correction);
  const { result } = renderHook(() => useKioskQueue("token", "space", "selected-failure"));
  await waitFor(() => expect(result.current.queue?.scope).toBe("correction"));
  expect(result.current.restored).toBe(true);
});
