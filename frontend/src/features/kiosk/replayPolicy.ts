import { StructuredApiError } from "../../lib/api/errors";
import type { LocalCommand } from "./offlineQueueTypes";

const AUTHORITY = new Set(["lease_expired", "station_revoked", "session_mismatch", "permission_revoked"]);
const DOMAIN_403 = new Set(["presence_expired", "membership_required", "waiver_required"]);
const RETRY = new Set(["claim_in_progress", "predecessor_pending", "rate_limited", "storage_unavailable", "server_unavailable"]);

export function classifyReplayError(error: unknown) {
  if (!(error instanceof StructuredApiError)) return { action: "retry" as const, code: "network_unavailable" };
  const code = error.code ?? "server_refused";
  if (AUTHORITY.has(code) || error.status === 401 || error.status === 410
      || (error.status === 403 && !DOMAIN_403.has(code))) return { action: "wipe" as const, code };
  if (RETRY.has(code) || error.status === 429 || error.status === 503) return { action: "retry" as const, code };
  return { action: "fail" as const, code };
}

export function retryDelay(attempt: number, random = Math.random) {
  return Math.round(Math.min(60_000, 1000 * 2 ** Math.min(attempt, 6)) * (0.75 + random() * 0.5));
}

export function runnableCommands(commands: LocalCommand[], now = Date.now()) {
  const streams = new Map<string, LocalCommand[]>();
  for (const command of commands) {
    const id = command.envelope.aggregate_id;
    streams.set(id, [...(streams.get(id) ?? []), command]);
  }
  return [...streams.values()].flatMap((stream) => {
    stream.sort((a, b) => a.envelope.sequence - b.envelope.sequence);
    const first = stream.find((cmd) => cmd.status !== "succeeded");
    return first && first.status !== "failed" && first.nextRetryAt <= now ? [first] : [];
  });
}
