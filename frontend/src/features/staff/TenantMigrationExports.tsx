import { useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  archiveSource,
  createMigrationExport,
  getMigrationExport,
  issueMigrationDownload,
  listDisclosureApprovals,
  listMigrationExports,
  quiesceSource,
  recoverSource,
  tenantMigrationKeys,
  type MigrationExportJob,
  type Pairing,
  type ReceiptEnvelope,
} from "./tenantMigrationApi";
import { ErrorText, openDownload, parseReceipt, ReceiptOutput, StatusPill } from "./tenantMigrationUi";

export function TenantMigrationExports({
  makerspaceId,
  tenantName,
  closureDigest,
  pairings,
}: {
  makerspaceId: number;
  tenantName: string;
  closureDigest?: string;
  pairings: Pairing[];
}) {
  const client = useQueryClient();
  const [approvalId, setApprovalId] = useState("");
  const [recipient, setRecipient] = useState("");
  const [abortReceipts, setAbortReceipts] = useState<Record<string, string>>({});
  const approvals = useQuery({
    queryKey: tenantMigrationKeys.approvals(makerspaceId),
    queryFn: () => listDisclosureApprovals(makerspaceId),
  });
  const exportsQuery = useQuery({
    queryKey: tenantMigrationKeys.exports(makerspaceId),
    queryFn: () => listMigrationExports(makerspaceId),
  });
  const exportDetails = useQueries({
    queries: (exportsQuery.data ?? []).map((job) => ({
      queryKey: tenantMigrationKeys.export(makerspaceId, job.id),
      queryFn: () => getMigrationExport(makerspaceId, job.id),
      refetchInterval: (query) => exportRunning((query.state.data as MigrationExportJob | undefined) ?? job) ? 1500 : false,
    })),
  });
  const validApprovals = approvals.data?.filter(
    (item) => !item.revoked_at && item.closure_digest === closureDigest,
  ) ?? [];
  const selectedApproval = approvalId || validApprovals[0]?.id || "";
  const createExport = useMutation({
    mutationFn: () => createMigrationExport(makerspaceId, {
      approval_id: selectedApproval,
      target_age_recipient: recipient.trim(),
    }),
    onSuccess: () => client.invalidateQueries({ queryKey: tenantMigrationKeys.exports(makerspaceId) }),
  });
  const download = useMutation({
    mutationFn: (jobId: string) => issueMigrationDownload(makerspaceId, jobId),
    onSuccess: ({ url }) => openDownload(url),
  });
  const quiesce = useMutation({
    mutationFn: (jobId: string) => quiesceSource(makerspaceId, jobId),
    onSuccess: (_data, jobId) => {
      client.invalidateQueries({ queryKey: tenantMigrationKeys.exports(makerspaceId) });
      client.invalidateQueries({ queryKey: tenantMigrationKeys.export(makerspaceId, jobId) });
    },
  });
  const archive = useMutation({
    mutationFn: (pairingId: string) => archiveSource(makerspaceId, pairingId),
    onSuccess: () => client.invalidateQueries({ queryKey: ["staff", "makerspaces"] }),
  });
  const recover = useMutation({
    mutationFn: ({ pairingId, receipt }: { pairingId: string; receipt: ReceiptEnvelope }) =>
      recoverSource(makerspaceId, pairingId, { receipt }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["staff", "makerspaces"] }),
  });

  return (
    <section aria-labelledby="migration-export-title" className="rounded-md border border-line bg-bg p-4">
      <p className="eyebrow">Source deployment</p>
      <h3 className="title-section" id="migration-export-title">Encrypted migration exports</h3>
      <p className="mt-2 text-sm text-ink">
        The target age recipient encrypts the portable archive for one target deployment. Quiescing
        freezes writes to {tenantName}. Archiving the source is a one-way cutover action from this screen.
      </p>
      <p className="mt-2 text-sm font-semibold text-danger">
        The source tenant is archived, not deleted, at cutover. Archives are outside the purge guarantee.
      </p>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <label className="text-sm text-ink">
          Approved closure
          <select className="desk-input mt-1 w-full" value={selectedApproval} onChange={(event) => setApprovalId(event.target.value)}>
            {validApprovals.length === 0 ? <option value="">Approve the current closure first</option> : null}
            {validApprovals.map((approval) => <option key={approval.id} value={approval.id}>{approval.approved_count}/{approval.identity_count} disclosed · {approval.id}</option>)}
          </select>
        </label>
        <label className="text-sm text-ink">
          Target age recipient
          <input className="desk-input mt-1 w-full font-mono" value={recipient} onChange={(event) => setRecipient(event.target.value)} placeholder="age1…" />
        </label>
      </div>
      <button className="desk-button-primary mt-3" type="button" disabled={!selectedApproval || !recipient.trim() || createExport.isPending} onClick={() => createExport.mutate()}>
        {createExport.isPending ? "Requesting encrypted export…" : "Create encrypted migration export"}
      </button>
      <ErrorText error={createExport.error} field="target_age_recipient" />

      {exportsQuery.isLoading ? <p className="mt-4 text-sm text-muted">Loading migration exports…</p> : null}
      <ErrorText error={exportsQuery.error} />
      <div className="mt-4 grid gap-3">
        {(exportsQuery.data ?? []).map((listedJob, index) => {
          const job = exportDetails[index]?.data ?? listedJob;
          const pairing = pairings.find((item) => item.archive_digest === job.archive_digest);
          const abortReceiptText = pairing ? abortReceipts[pairing.id] ?? "" : "";
          const abortReceipt = parseReceipt(abortReceiptText);
          return (
            <article className="rounded-md border border-line bg-surface p-3" key={job.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-semibold text-ink">Export {job.id}</p>
                  <p className="mt-1 break-all font-mono text-xs text-muted">Archive digest: {job.archive_digest || "Pending"}</p>
                </div>
                <StatusPill tone={job.status === "failed" ? "danger" : job.status === "available" ? "success" : "warn"}>{(job.status ?? "pending").toUpperCase()}</StatusPill>
              </div>
              {job.failure_detail ? <p className="mt-2 text-sm text-danger" role="alert">{job.failure_detail}</p> : null}
              <ErrorText error={exportDetails[index]?.error} />
              <p className="mt-2 text-xs text-muted">{job.source_retention_notice}</p>
              {quiesce.isSuccess && quiesce.variables === job.id ? <p className="mt-2 text-sm font-semibold text-danger" role="status">Source writes are frozen for this cutover.</p> : null}
              {job.status === "available" ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  <button className="desk-button" type="button" disabled={download.isPending} onClick={() => download.mutate(job.id)}>Download one-use archive</button>
                  <button className="desk-button-danger" type="button" disabled={quiesce.isPending} onClick={() => {
                    if (window.confirm(`Quiesce ${tenantName}? This freezes source writes before cutover.`)) quiesce.mutate(job.id);
                  }}>Quiesce {tenantName}</button>
                  {pairing ? <button className="desk-button-danger" type="button" disabled={archive.isPending} onClick={() => {
                    if (window.confirm(`Archive ${tenantName}? This source cutover cannot be undone from this screen.`)) archive.mutate(pairing.id);
                  }}>Archive source {tenantName}</button> : null}
                </div>
              ) : null}
              {pairing ? (
                <div className="mt-3 rounded-md border border-line p-3">
                  <p className="text-xs text-muted">Pinned pairing <span className="font-mono">{pairing.id}</span></p>
                  <label className="mt-2 block text-sm text-ink">
                    Target ABORTED receipt (only for recovery after target abort)
                    <textarea className="desk-input mt-1 min-h-24 w-full font-mono text-xs" value={abortReceiptText} onChange={(event) => setAbortReceipts((current) => ({ ...current, [pairing.id]: event.target.value }))} />
                  </label>
                  <button className="desk-button-danger mt-2" type="button" disabled={!abortReceipt || recover.isPending} onClick={() => {
                    if (abortReceipt && window.confirm(`Recover archived source ${tenantName}? Use only after the target is ABORTED.`)) recover.mutate({ pairingId: pairing.id, receipt: abortReceipt });
                  }}>Recover source {tenantName}</button>
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
      <ErrorText error={download.error ?? quiesce.error ?? archive.error ?? recover.error} field="receipt" />
      <ReceiptOutput label="Source cutover receipt — transfer to target" receipt={archive.data?.receipt} />
      {recover.data ? <p className="mt-3 text-sm text-success-ink" role="status">{recover.data.message}</p> : null}
    </section>
  );
}

function exportRunning(job: MigrationExportJob) {
  return job.status === "pending" || job.status === "running";
}
