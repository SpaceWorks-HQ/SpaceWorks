import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { addMachineErrorLog, collectionResults, getMachineErrorLogs, machineKeys } from "../../machinesApi";

export function ErrorsTab({ machineId, canOperate }: { machineId: number; canOperate: boolean }) {
  const queryClient = useQueryClient();
  const [severity, setSeverity] = useState("error");
  const [message, setMessage] = useState("");
  const logs = useQuery({
    queryKey: machineKeys.errors(machineId),
    queryFn: () => getMachineErrorLogs(machineId),
  });
  const items = collectionResults(logs.data);
  const add = useMutation({
    mutationFn: () => addMachineErrorLog(machineId, {
      severity: severity.trim(),
      message: message.trim(),
    }),
    onSuccess: async () => {
      setMessage("");
      await queryClient.invalidateQueries({ queryKey: machineKeys.errors(machineId) });
    },
  });

  return (
    <section>
      <h3 className="title-section mb-3">Error logs</h3>
      {logs.isLoading ? <p className="text-sm text-muted">Loading error logs...</p> : null}
      {logs.error instanceof Error ? <p className="text-sm text-danger">{logs.error.message}</p> : null}
      {!logs.isLoading && !logs.error && !items.length ? (
        <p className="text-sm text-muted">No errors logged.</p>
      ) : null}
      <div className="grid gap-2">
        {items.map((entry) => (
          <div key={entry.id} className="rounded-md border border-line bg-bg p-2 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <strong className="text-ink">{entry.severity}</strong>
              <span className="font-mono text-xs text-muted">{formatDate(entry.created_at)}</span>
            </div>
            <p className="mt-1 whitespace-pre-wrap break-words text-muted">{entry.message}</p>
            {entry.logged_by_username ? (
              <p className="mt-1 text-xs text-muted">Logged by {entry.logged_by_username}</p>
            ) : null}
          </div>
        ))}
      </div>
      {canOperate ? (
        <form className="mt-3 grid gap-2" onSubmit={(event) => { event.preventDefault(); add.mutate(); }}>
          <label className="eyebrow grid gap-1">Severity
            <input className="desk-input" maxLength={16} value={severity}
              onChange={(event) => setSeverity(event.target.value)} required />
          </label>
          <label className="eyebrow grid gap-1">Message
            <textarea className="desk-input min-h-20" value={message}
              onChange={(event) => setMessage(event.target.value)} required />
          </label>
          <button className="desk-button-primary justify-self-start" type="submit"
            disabled={add.isPending || !severity.trim() || !message.trim()}>
            {add.isPending ? "Logging..." : "Add error log"}
          </button>
        </form>
      ) : null}
      {add.error instanceof Error ? <p className="mt-2 text-sm text-danger">{add.error.message}</p> : null}
    </section>
  );
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
