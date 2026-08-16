import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  decideRestore,
  getBackupSettings,
  getRestore,
  issueBackupDownload,
  listDeploymentBackups,
  listRestores,
  listTenantBackups,
  requestDeploymentBackup,
  requestRestore,
  requestTenantBackup,
  updateBackupSettings,
  type BackupArchive,
} from "./backupApi";
import { Panel } from "./panels/shared";

export function BackupRestorePanel({ makerspaceId, isSuperadmin }: { makerspaceId: number; isSuperadmin: boolean }) {
  const client = useQueryClient();
  const tenantKey = ["tenant-backups", makerspaceId];
  const deploymentKey = ["deployment-backups"];
  const tenant = useQuery({ queryKey: tenantKey, queryFn: () => listTenantBackups(makerspaceId), refetchInterval: pollArchives });
  const deployment = useQuery({ queryKey: deploymentKey, queryFn: listDeploymentBackups, enabled: isSuperadmin, refetchInterval: pollArchives });
  const settings = useQuery({ queryKey: ["backup-settings"], queryFn: getBackupSettings, enabled: isSuperadmin });
  const restores = useQuery({ queryKey: ["restore-operations"], queryFn: listRestores, enabled: isSuperadmin, refetchInterval: 3000 });
  const activeRestore = restores.data?.find((row) => !["completed", "failed", "aborted", "restored_quarantined"].includes(row.stage));
  const restoreDetail = useQuery({ queryKey: ["restore-operation", activeRestore?.id], queryFn: () => getRestore(activeRestore!.id), enabled: Boolean(activeRestore), refetchInterval: 1000 });
  const createTenant = useMutation({ mutationFn: () => requestTenantBackup(makerspaceId), onSuccess: () => client.invalidateQueries({ queryKey: tenantKey }) });
  const createDeployment = useMutation({ mutationFn: requestDeploymentBackup, onSuccess: () => client.invalidateQueries({ queryKey: deploymentKey }) });
  const saveSettings = useMutation({ mutationFn: updateBackupSettings, onSuccess: (data) => client.setQueryData(["backup-settings"], data) });
  const download = useMutation({ mutationFn: issueBackupDownload, onSuccess: ({ url }) => window.location.assign(url) });
  const startRestore = useMutation({ mutationFn: ({ archive, kind }: { archive: string; kind: "rollback_in_place" | "disaster" }) => requestRestore(archive, kind), onSuccess: () => client.invalidateQueries({ queryKey: ["restore-operations"] }) });
  const decision = useMutation({ mutationFn: ({ id, value }: { id: string; value: "proceed" | "reset" | "abort" }) => decideRestore(id, value), onSuccess: () => client.invalidateQueries({ queryKey: ["restore-operations"] }) });

  return (
    <div className="grid gap-5">
      <Panel title="Makerspace backups">
        <ArchiveDisclosure deployment={false} />
        <ActionButton label="Create makerspace archive" pending={createTenant.isPending} onClick={() => createTenant.mutate()} />
        <ArchiveRows rows={tenant.data ?? []} onDownload={(id) => download.mutate(id)} />
      </Panel>
      {isSuperadmin ? (
        <Panel title="Deployment backup and restore">
          <div className="grid gap-4">
            <ArchiveDisclosure deployment />
            <label className="flex items-center gap-3 text-sm text-ink">
              <input type="checkbox" checked={settings.data?.automatic_backups_enabled ?? false} disabled={saveSettings.isPending} onChange={(event) => saveSettings.mutate({ automatic_backups_enabled: event.target.checked })} />
              Create a full deployment archive each day
            </label>
            <p className="text-xs text-muted">Last successful archive: {formatDate(settings.data?.last_success_at)}</p>
            <label className="grid max-w-xs gap-1 text-sm text-ink">
              Archive retention (days)
              <input className="desk-input" type="number" min={1} max={3650} key={settings.data?.retention_days} defaultValue={settings.data?.retention_days ?? 30} onBlur={(event) => saveSettings.mutate({ retention_days: Math.max(1, Number(event.target.value) || 30) })} />
            </label>
            {settings.data?.last_error ? <p className="text-sm text-danger" role="alert">{settings.data.last_error}</p> : null}
            <ActionButton label="Create full deployment archive" pending={createDeployment.isPending} onClick={() => createDeployment.mutate()} />
            <ArchiveRows rows={deployment.data ?? []} onDownload={(id) => download.mutate(id)} onRestore={(id, kind) => startRestore.mutate({ archive: id, kind })} />
            {restoreDetail.data ? <RestoreDecision operation={restoreDetail.data} onDecide={(value) => decision.mutate({ id: restoreDetail.data!.id, value })} /> : null}
          </div>
        </Panel>
      ) : null}
      {tenant.error || deployment.error || settings.error || restores.error || createTenant.error || createDeployment.error || saveSettings.error || download.error || startRestore.error || decision.error ? (
        <p className="text-sm text-danger" role="alert">A backup operation failed. Refresh for the persisted status.</p>
      ) : null}
    </div>
  );
}

function ArchiveDisclosure({ deployment }: { deployment: boolean }) {
  return <p className="rounded-md border border-warn/40 bg-warn/10 p-3 text-sm text-ink">This {deployment ? "deployment archive contains production data and continuity secrets" : "makerspace archive contains production tenant data"}, encrypted to the configured age recipient. Downloaded copies are outside makerspace purge guarantees; delete retained copies separately.</p>;
}

function ArchiveRows({ rows, onDownload, onRestore }: { rows: BackupArchive[]; onDownload: (id: string) => void; onRestore?: (id: string, kind: "rollback_in_place" | "disaster") => void }) {
  return <div className="grid gap-2">{rows.length === 0 ? <p className="text-sm text-muted">No backup archives yet.</p> : rows.map((row) => (
    <article key={row.id} className="rounded-md border border-line p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><p className="font-medium text-ink">{row.scope === "deployment" ? "Full deployment" : "Makerspace"}</p><p className="text-xs text-muted">{new Date(row.created_at).toLocaleString()} · {row.status} · {formatBytes(row.size_bytes)}</p></div>
        <div className="flex flex-wrap gap-2">{row.status === "available" ? <button className="desk-button" type="button" onClick={() => onDownload(row.id)}>Download</button> : null}{onRestore && row.status === "available" ? <><button className="desk-button" type="button" onClick={() => onRestore(row.id, "rollback_in_place")}>Rollback here</button><button className="desk-button-danger" type="button" onClick={() => onRestore(row.id, "disaster")}>Disaster restore</button></> : null}</div>
      </div>{row.failure_detail ? <p className="mt-2 text-sm text-danger">{row.failure_detail}</p> : null}
    </article>
  ))}</div>;
}

function RestoreDecision({ operation, onDecide }: { operation: Awaited<ReturnType<typeof getRestore>>; onDecide: (value: "proceed" | "reset" | "abort") => void }) {
  const waiting = operation.stage === "quiesced" && operation.decision === "pending" && operation.decision_deadline_at;
  const seconds = waiting ? Math.max(0, Math.ceil((new Date(operation.decision_deadline_at!).getTime() - Date.now()) / 1000)) : 0;
  return <section className="rounded-md border border-danger/40 bg-danger/5 p-4"><h3 className="title-section">Restore {operation.stage}</h3><p className="mt-1 text-sm text-muted">{operation.restore_diff.tables_compared ?? 0} tables compared; {operation.restore_diff.tables_changed ?? 0} differ.</p><div className="mt-3 grid max-h-72 gap-2 overflow-auto">{operation.restore_diff.tables?.map((table) => <details key={table.table} className="rounded border border-line bg-surface p-2"><summary className="cursor-pointer text-sm text-ink"><span className="font-mono">{table.table}</span> · {table.live.row_count} live / {table.archive.row_count} archived {table.security_relevant ? "· security-relevant" : ""} {table.noisy ? "· noisy" : ""}</summary>{table.row_diff ? <pre className="mt-2 overflow-auto text-xs text-muted">{JSON.stringify(table.row_diff, null, 2)}</pre> : null}</details>)}</div>{waiting ? <><p className="mt-2 font-mono text-sm">Decision window: {seconds}s</p><p className="mt-2 text-sm text-ink">Proceed only after reviewing the all-table report. “Reset authority” quarantines every principal and invalidates restored credentials.</p><div className="mt-3 flex flex-wrap gap-2"><button className="desk-button-primary" onClick={() => onDecide("proceed")}>Proceed</button><button className="desk-button" onClick={() => onDecide("reset")}>Proceed and reset authority</button><button className="desk-button-danger" onClick={() => onDecide("abort")}>Abort safely</button></div></> : null}</section>;
}

function ActionButton({ label, pending, onClick }: { label: string; pending: boolean; onClick: () => void }) { return <button className="desk-button-primary w-fit" type="button" disabled={pending} onClick={onClick}>{pending ? "Requesting…" : label}</button>; }
function pollArchives(query: { state: { data?: BackupArchive[] } }) { return query.state.data?.some((row) => row.status === "pending" || row.status === "running") ? 2000 : false; }
function formatDate(value?: string | null) { return value ? new Date(value).toLocaleString() : "Never"; }
function formatBytes(value: number) { return value ? `${(value / 1024 / 1024).toFixed(1)} MB` : "—"; }
