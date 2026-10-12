import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { decideRestore, getRestore } from "./backupApi";
import { RestoreDecision } from "./BackupRestorePanel";
import { recoverUpdate, rollbackUpdate, UPDATE_QUERY_KEY, type PlatformUpdateSettings } from "./platformUpdateApi";

export function UpdateRecoveryControls({ data, busy }: { data: PlatformUpdateSettings; busy: boolean }) {
  const client = useQueryClient();
  const [snapshot, setSnapshot] = useState<{ archive_id: string; confirm_version: string } | null>(null);
  const [confirmLoss, setConfirmLoss] = useState(false);
  const [confirmImages, setConfirmImages] = useState(false);
  const [requestedId, setRequestedId] = useState<string | null>(null);
  const recovery = useMutation({
    mutationFn: recoverUpdate,
    onSuccess: (row) => client.setQueryData(UPDATE_QUERY_KEY, row),
  });
  const rollback = useMutation({
    mutationFn: rollbackUpdate,
    onSuccess: ({ id }) => {
      setRequestedId(id);
      setSnapshot(null);
      void client.invalidateQueries({ queryKey: UPDATE_QUERY_KEY });
      void client.invalidateQueries({ queryKey: ["restore-operations"] });
    },
  });
  const restoreId = requestedId ?? data.rollback_restore;
  const restore = useQuery({
    queryKey: ["restore-operation", restoreId], queryFn: () => getRestore(restoreId!),
    enabled: Boolean(restoreId), refetchInterval: (query) =>
      query.state.data && ["completed", "restored_quarantined", "failed", "aborted"].includes(query.state.data.stage) ? false : 1000,
  });
  const decision = useMutation({
    mutationFn: (value: "proceed" | "reset" | "abort") => decideRestore(restoreId!, value),
    onSuccess: (row) => {
      client.setQueryData(["restore-operation", restoreId], row);
      void client.invalidateQueries({ queryKey: UPDATE_QUERY_KEY });
    },
  });
  const disabled = busy || recovery.isPending || rollback.isPending || data.status === "running" || data.status === "queued" || data.rollback_active;
  const error = recovery.error || rollback.error || restore.error || decision.error;

  return <section className="space-y-3 border-t border-line pt-4" aria-labelledby="update-recovery-title">
    <h3 className="title-section" id="update-recovery-title">Recovery and rollback</h3>
    {data.is_stuck ? <>
      <p className="text-sm text-warn-ink">This update has exceeded its running timeout. Recovery checks that the host operation is no longer active.</p>
      <button type="button" className="desk-button" disabled={busy || recovery.isPending} onClick={() => recovery.mutate()}>
        {recovery.isPending ? "Recovering..." : "Recover interrupted update"}
      </button>
    </> : null}
    {data.rollback_available ? <>
      <p className="text-sm text-muted">Restore point for SpaceWorks {data.pre_update_version}. Rollback replaces the deployment database, archived objects and application images. Changes since the snapshot will be lost.</p>
      <button type="button" className="desk-button-danger" disabled={disabled} onClick={() => {
        if (data.pre_update_archive) {
          setSnapshot({ archive_id: data.pre_update_archive, confirm_version: data.pre_update_version });
          setConfirmLoss(false);
          setConfirmImages(false);
        }
      }}>Roll back to pre-update snapshot</button>
    </> : <p className="text-sm text-muted">Rollback unavailable ({data.rollback_refusal || "no_snapshot"}). {data.rollback_refusal_detail || "Legacy database-only backups require host recovery."}</p>}
    {snapshot ? <div className="space-y-3 rounded-md border border-danger/40 p-3">
      <p className="text-sm text-ink">Confirm restore to SpaceWorks {snapshot.confirm_version}.</p>
      <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={confirmLoss} onChange={(event) => setConfirmLoss(event.target.checked)} />I understand changes since this snapshot will be lost.</label>
      <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={confirmImages} onChange={(event) => setConfirmImages(event.target.checked)} />Restore the database and previous application version.</label>
      <p className="text-sm text-muted">The host starts at its next scheduled check. Review the all-table restore diff and choose Proceed before the decision window expires.</p>
      <div className="flex gap-2">
        <button type="button" className="desk-button-danger" disabled={disabled || !confirmLoss || !confirmImages} onClick={() => rollback.mutate(snapshot)}>{rollback.isPending ? "Requesting..." : "Confirm rollback"}</button>
        <button type="button" className="desk-button" disabled={rollback.isPending} onClick={() => setSnapshot(null)}>Cancel</button>
      </div>
    </div> : null}
    {restore.data ? <>
      <p className="text-sm text-muted">Rollback restore: {restore.data.stage}. {restore.data.error_detail}</p>
      <RestoreDecision operation={restore.data} onDecide={(value) => { if (!decision.isPending) decision.mutate(value); }} />
    </> : null}
    {error ? <p role="alert" className="text-sm text-danger">{error.message}</p> : null}
  </section>;
}
