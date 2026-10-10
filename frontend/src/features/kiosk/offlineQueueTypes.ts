import type { KioskBootstrap, KioskLease, KioskWorkPackage } from "./kioskApi";
import type { ReplayEnvelope, ReplayResult } from "./kioskReplayApi";

export const KIOSK_DB = "spaceworks-kiosk-v1";
export const MAX_PENDING_COMMANDS = 50;
export const MAX_EVIDENCE_BYTES = 100 * 1024 * 1024;
export type CommandStatus = "queued" | "preparing" | "uploading" | "executing" | "succeeded" | "failed";
export type LocalCommand = {
  envelope: ReplayEnvelope;
  workPackageId: string;
  evidenceRecordId: string | null;
  status: CommandStatus;
  attempts: number;
  nextRetryAt: number;
  lastFailure: string | null;
  result: ReplayResult | null;
  uploaded: boolean;
};
export type LoadedWork = { id: string; aggregateId: string; work: KioskWorkPackage };
export type OfflineQueue = {
  version: 1;
  scope: string;
  token: string;
  apiBase: string;
  session: KioskBootstrap;
  lease: KioskLease;
  works: LoadedWork[];
  commands: LocalCommand[];
};

export function kioskScope(session: KioskBootstrap, lease: KioskLease) {
  if (!lease.session_id || !lease.actor_id) throw new Error("Reconnect to obtain an offline-capable operator lease.");
  return `${session.makerspace.id}/${session.station.id}/${lease.session_id}/${lease.lease_id}/${lease.actor_id}`;
}

export function queueDeadline(state: OfflineQueue) {
  return new Date(Math.min(
    Date.parse(state.session.session_expires_at), Date.parse(state.lease.expires_at),
    ...state.works.map(({ work }) => Date.parse(work.expires_at)),
    ...state.commands.map(({ envelope, workPackageId }) => Date.parse(envelope.client_created_at)
      + (state.works.find((item) => item.id === workPackageId)?.work.command_age_limit_seconds ?? 0) * 1000),
  )).toISOString();
}
