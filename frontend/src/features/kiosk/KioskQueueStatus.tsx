import type { OfflineQueue } from "./offlineQueueTypes";

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
    </li>)}</ol>
    {failed ? <p className="text-sm text-danger">Failed work needs staff review. Other handovers can continue.</p> : null}
    <div className="flex flex-wrap gap-2">
      <button type="button" className="desk-button-secondary" onClick={retry}>Retry queued work</button>
      {complete ? <button type="button" className="desk-button-secondary" onClick={acknowledge}>Acknowledge completion and clear local work</button> : null}
    </div>
  </section>;
}
