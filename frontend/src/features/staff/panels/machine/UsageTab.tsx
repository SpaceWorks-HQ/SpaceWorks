import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { addMachineUsage, collectionResults, getMachineUsage, machineKeys } from "../../machinesApi";

export function UsageTab({ machineId, makerspaceId, canOperate }: {
  machineId: number;
  makerspaceId: number;
  canOperate: boolean;
}) {
  const queryClient = useQueryClient();
  const [hours, setHours] = useState("");
  const [note, setNote] = useState("");
  const usage = useQuery({
    queryKey: machineKeys.usage(machineId),
    queryFn: () => getMachineUsage(machineId),
  });
  const items = collectionResults(usage.data);
  const add = useMutation({
    mutationFn: () => addMachineUsage(machineId, { hours, note: note.trim() }),
    onSuccess: async () => {
      setHours("");
      setNote("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: machineKeys.usage(machineId) }),
        queryClient.invalidateQueries({ queryKey: machineKeys.detail(machineId) }),
        queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) }),
      ]);
    },
  });

  return (
    <section>
      <h3 className="title-section mb-3">Usage</h3>
      {usage.isLoading ? <p className="text-sm text-muted">Loading usage...</p> : null}
      {usage.error instanceof Error ? <p className="text-sm text-danger">{usage.error.message}</p> : null}
      {!usage.isLoading && !usage.error && !items.length ? (
        <p className="text-sm text-muted">No usage logged yet.</p>
      ) : null}
      <div className="grid gap-2">
        {items.map((entry) => (
          <div key={entry.id} className="rounded-md border border-line bg-bg p-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <strong className="font-mono text-ink">{entry.hours} h</strong>
              <span className="font-mono text-xs text-muted">{formatDate(entry.created_at)}</span>
            </div>
            {entry.note ? <p className="mt-1 break-words text-muted">{entry.note}</p> : null}
            <p className="mt-1 text-xs text-muted">
              {entry.source}{entry.logged_by_username ? ` · ${entry.logged_by_username}` : ""}
            </p>
          </div>
        ))}
      </div>
      {canOperate ? (
        <form className="mt-3 grid gap-2 sm:grid-cols-[8rem_minmax(0,1fr)_auto] sm:items-end"
          onSubmit={(event) => { event.preventDefault(); add.mutate(); }}>
          <label className="eyebrow grid gap-1">Hours
            <input className="desk-input" type="number" min="0.01" step="0.01" value={hours}
              onChange={(event) => setHours(event.target.value)} required />
          </label>
          <label className="eyebrow grid gap-1">Note
            <input className="desk-input" maxLength={255} value={note}
              onChange={(event) => setNote(event.target.value)} />
          </label>
          <button className="desk-button-primary" type="submit" disabled={add.isPending || !hours}>
            {add.isPending ? "Logging..." : "Add usage"}
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
