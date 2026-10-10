import type { OfflineQueue } from "./offlineQueueTypes";
import { replayGuidance } from "./replayRecoveryGuidance";

export function KioskQueueStatus({ queue, retry, acknowledge }: {
  queue: OfflineQueue; retry: () => void; acknowledge: () => void;
}) {
  const pending = queue.commands.filter((item) => !["succeeded", "failed"].includes(item.status)).length;
  const failed = queue.commands.filter((item) => item.status === "failed").length;
  const complete = queue.commands.length > 0 && queue.commands.every((item) => item.status === "succeeded");
  return <section className="grid gap-2" aria-label="Handover queue">
    <p className="text-sm" role="status">{pending} pending · {failed} failed</p>
    <ol className="grid gap-2 text-sm">{queue.commands.map((command) => <li key={command.envelope.client_command_id}>
      Sequence {command.envelope.sequence} · {command.envelope.kind} · {command.status === "queued" ? "Queued" : command.status}
      {command.lastFailure ? ` · ${command.lastFailure}` : ""}
      {command.status === "failed" ? <div className="grid gap-1">
        <p>{replayGuidance(command.lastFailure)}</p>
        {command.result?.replay_id ? <a className="desk-button-secondary" href={`${window.location.pathname}?recovery=${encodeURIComponent(command.result.replay_id)}`}>Review failed handover online</a> :
          <p>No server recovery record was confirmed. Keep this local evidence for staff review.</p>}
      </div> : null}
    </li>)}</ol>
    {failed ? <p className="text-sm text-danger">Failed work needs staff review. Other handovers can continue.</p> : null}
    <div className="flex flex-wrap gap-2">
      <button type="button" className="desk-button-secondary" onClick={retry}>Retry queued work</button>
      {complete ? <button type="button" className="desk-button-secondary" onClick={acknowledge}>Acknowledge completion and clear local work</button> : null}
    </div>
  </section>;
}
