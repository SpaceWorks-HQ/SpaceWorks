import { StructuredApiError } from "../../lib/api/errors";
import { prepareReplay, executeReplay } from "./kioskReplayApi";
import type { ReplayResult } from "./kioskReplayApi";
import type { UploadResponse } from "../staff/panels/EvidenceUpload";
import { loadQueue, updateCommand, readEvidence, destroyQueue } from "./offlineQueueStore";
import { withReplayLock } from "./offlineQueueDb";
import { classifyReplayError, retryDelay, runnableCommands } from "./replayPolicy";
import type { LocalCommand, OfflineQueue } from "./offlineQueueTypes";

export async function uploadReplayEvidence(upload: UploadResponse, photo: Blob) {
  let response: Response;
  if (upload.method === "PUT") {
    response = await fetch(upload.upload_url, { method: "PUT", body: photo,
      headers: upload.headers, credentials: "omit", cache: "no-store", signal: AbortSignal.timeout(60_000) });
  } else {
    const form = new FormData();
    Object.entries(upload.fields).forEach(([key, value]) => form.append(key, value));
    form.append("file", photo, "evidence.jpg");
    response = await fetch(upload.upload_url, { method: "POST", body: form,
      headers: upload.headers, credentials: "omit", cache: "no-store", signal: AbortSignal.timeout(60_000) });
  }
  // A storage 403 is an expired presign, not revoked Station authority. Prepare a
  // fresh staging presign next time; never persist its URL or response text.
  if (!response.ok) throw new StructuredApiError(503, { code: "storage_unavailable" });
}

async function runCommand(queue: OfflineQueue, command: LocalCommand) {
  const scope = queue.scope;
  const id = command.envelope.client_command_id;
  const attempts = command.attempts + 1;
  const update = (patch: Partial<LocalCommand>) => updateCommand(scope, id, patch);
  const finish = async (result: ReplayResult) => {
    if (result.state === "succeeded" || result.state === "failed") {
      await update({ result, status: result.state, lastFailure: result.failure_code, nextRetryAt: 0 });
      return true;
    }
    return false;
  };
  try {
    if (!await update({ status: "preparing", attempts })) return false;
    const prepared = await prepareReplay(queue.token, queue.lease.lease_token, command.envelope, queue.apiBase);
    if (await finish(prepared)) return true;
    if (prepared.state === "claimed") throw new StructuredApiError(409, { code: "claim_in_progress" });
    if (!await update({ result: { ...prepared, upload: undefined } })) return false;
    if (prepared.upload && command.evidenceRecordId && !command.uploaded) {
      if (!await update({ status: "uploading" })) return false;
      let bytes: ArrayBuffer | null = await readEvidence(scope, command.evidenceRecordId);
      try {
        await uploadReplayEvidence(prepared.upload, new Blob([bytes], { type: command.envelope.evidence?.content_type }));
      } finally { new Uint8Array(bytes).fill(0); bytes = null; }
      if (!await update({ uploaded: true })) return false;
    }
    if (!await update({ status: "executing" })) return false;
    const result = await executeReplay(queue.token, queue.lease.lease_token, command.envelope, queue.apiBase);
    if (!await finish(result)) throw new StructuredApiError(409, { code: "claim_in_progress" });
    return true;
  } catch (error) {
    const failure = classifyReplayError(error);
    if (failure.action === "wipe") { await destroyQueue(scope); return false; }
    await update({ status: failure.action === "retry" ? "queued" : "failed", lastFailure: failure.code,
      nextRetryAt: failure.action === "retry" ? Date.now() + retryDelay(attempts) : 0 });
    return false;
  }
}

// Shared by the foreground and SW. Web Locks prevent simultaneous upload/execute
// and make explicit reset wait until a physical operation has finished.
export function replayQueue(scope: string) {
  return withReplayLock(scope, async () => {
    for (let pass = 0; pass < 50; pass += 1) {
      const queue = await loadQueue(scope);
      if (!queue) return;
      const runnable = runnableCommands(queue.commands);
      if (!runnable.length) return;
      let progressed = false;
      for (const command of runnable) {
        progressed = await runCommand(queue, command) || progressed;
        if (!await loadQueue(scope)) return;
      }
      if (!progressed) return;
    }
  });
}
