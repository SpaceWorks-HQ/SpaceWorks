import { afterEach, describe, expect, it, vi } from "vitest";
import { executeReplay, prepareReplay } from "./kioskReplayApi";
import type { ReplayEnvelope } from "./kioskReplayApi";

afterEach(() => vi.unstubAllGlobals());

const envelope: ReplayEnvelope = {
  kind: "assign_box", version: 1, client_command_id: "command-id", aggregate_id: "aggregate-id",
  sequence: 1, client_created_at: "2026-10-10T12:00:00Z", payload: { request_id: 1, box_code: "box" },
};

describe("replay API bearer transport", () => {
  it("sends the same envelope with Station cookie and lease to both protocol routes", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ state: "prepared" }) });
    vi.stubGlobal("fetch", fetcher);
    await prepareReplay("station-token", "human-lease", envelope);
    await executeReplay("station-token", "human-lease", envelope);
    expect(fetcher.mock.calls[0][0]).toContain("/station-token/replay/prepare/");
    expect(fetcher.mock.calls[1][0]).toContain("/replay/command-id/execute/");
    for (const [, options] of fetcher.mock.calls) {
      expect(options.credentials).toBe("include");
      expect(options.cache).toBe("no-store");
      expect(options.headers["X-Kiosk-Operator-Lease"]).toBe("human-lease");
      expect(options.headers["Authorization"]).toBeUndefined();
      expect(options.body).toBe(JSON.stringify(envelope));
    }
  });

  it("preserves typed conflict and transient failures without refreshing normal login", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 409,
      json: async () => ({ code: "claim_in_progress", detail: "Another caller is executing." }) });
    vi.stubGlobal("fetch", fetcher);
    await expect(executeReplay("station-token", "lease", envelope)).rejects.toMatchObject({
      status: 409, code: "claim_in_progress",
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
