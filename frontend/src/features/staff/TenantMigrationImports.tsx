import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  abortTarget,
  activateTarget,
  createImport,
  getImport,
  getVerification,
  listImports,
  runImport,
  tenantMigrationKeys,
  type ImportJob,
  type Pairing,
  type ReceiptEnvelope,
  type VerificationReport,
} from "./tenantMigrationApi";
import { TenantMigrationIdentityDecisions } from "./TenantMigrationIdentityDecisions";
import { ErrorText, parseReceipt, ReceiptOutput, StatusPill } from "./tenantMigrationUi";

export function TenantMigrationImports({ pairings }: { pairings: Pairing[] }) {
  const client = useQueryClient();
  const [archive, setArchive] = useState<File | null>(null);
  const [digest, setDigest] = useState("");
  const imports = useQuery({
    queryKey: tenantMigrationKeys.imports,
    queryFn: listImports,
  });
  const create = useMutation({
    mutationFn: () => createImport({ archive: archive!, source_archive_digest: digest.trim() }),
    onSuccess: () => client.invalidateQueries({ queryKey: tenantMigrationKeys.imports }),
  });

  return (
    <section aria-labelledby="migration-import-title" className="rounded-md border border-line bg-bg p-4">
      <p className="eyebrow">Target deployment</p>
      <h3 className="title-section" id="migration-import-title">Import and verify target</h3>
      <p className="mt-2 text-sm text-ink">Upload the age-encrypted archive and bind it to the digest shown on the source export. Materialization creates an IMPORTING tenant; it is not live until separately activated.</p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <label className="text-sm text-ink">Encrypted archive<input className="desk-input mt-1 w-full" type="file" onChange={(event) => setArchive(event.target.files?.[0] ?? null)} /></label>
        <label className="text-sm text-ink">Source archive digest<input className="desk-input mt-1 w-full font-mono" value={digest} onChange={(event) => setDigest(event.target.value)} /></label>
      </div>
      <button className="desk-button-primary mt-3" type="button" disabled={!archive || !digest.trim() || create.isPending} onClick={() => create.mutate()}>
        {create.isPending ? "Uploading encrypted archive…" : "Create target import"}
      </button>
      <ErrorText error={create.error} field="source_archive_digest" />
      {imports.isLoading ? <p className="mt-4 text-sm text-muted">Loading import jobs…</p> : null}
      <ErrorText error={imports.error} />
      <div className="mt-4 grid gap-4">
        {(imports.data ?? []).map((job) => (
          <ImportJobCard job={job} key={job.id} pairing={pairings.find((item) => item.migration_id === job.id)} />
        ))}
      </div>
    </section>
  );
}

function ImportJobCard({ job: listedJob, pairing }: { job: ImportJob; pairing?: Pairing }) {
  const client = useQueryClient();
  const [targetName, setTargetName] = useState("");
  const [targetSlug, setTargetSlug] = useState("");
  const [reviewedIdentities, setReviewedIdentities] = useState(false);
  const [sourceReceiptText, setSourceReceiptText] = useState("");
  const detail = useQuery({
    queryKey: tenantMigrationKeys.import(listedJob.id),
    queryFn: () => getImport(listedJob.id),
    refetchInterval: (query) => importRunning((query.state.data as ImportJob | undefined) ?? listedJob) ? 1500 : false,
  });
  const job = detail.data ?? listedJob;
  const sourceReceipt = parseReceipt(sourceReceiptText);
  const tenantName = targetName.trim() || job.source_makerspace_name || "imported tenant";
  const verification = useQuery({
    queryKey: tenantMigrationKeys.verification(job.id),
    queryFn: () => getVerification(job.id),
    enabled: job.status === "completed",
    retry: false,
  });
  const refreshJob = (next?: ImportJob) => {
    if (next) client.setQueryData(tenantMigrationKeys.import(job.id), next);
    client.invalidateQueries({ queryKey: tenantMigrationKeys.imports });
    client.invalidateQueries({ queryKey: tenantMigrationKeys.import(job.id) });
  };
  const run = useMutation({
    mutationFn: () => runImport(job.id, {
      target_identity: {
        ...(targetName.trim() ? { name: targetName.trim() } : {}),
        ...(targetSlug.trim() ? { slug: targetSlug.trim() } : {}),
      },
    }),
    onSuccess: refreshJob,
  });
  const activate = useMutation({
    mutationFn: (receipt: ReceiptEnvelope) => activateTarget(job.id, pairing!.id, { receipt }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: tenantMigrationKeys.imports });
      client.invalidateQueries({ queryKey: tenantMigrationKeys.verification(job.id) });
      client.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
    },
  });
  const abort = useMutation({
    mutationFn: () => abortTarget(job.id, pairing!.id),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: tenantMigrationKeys.imports });
      client.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
    },
  });
  const lifecycle = activate.data ? "ACTIVE" : abort.data ? "ABORTED" :
    (job.status === "materializing" || job.status === "completed") ? "IMPORTING" : (job.status ?? "pending").toUpperCase();
  const tone: "success" | "danger" | "warn" = lifecycle === "ACTIVE" ? "success" : lifecycle === "ABORTED" || job.status === "failed" ? "danger" : "warn";

  return (
    <article className="rounded-md border border-line bg-surface p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-ink">{job.source_makerspace_name || "Pending archive inspection"}</p>
          <p className="mt-1 font-mono text-xs text-muted">Import {job.id}</p>
        </div>
        <StatusPill tone={tone}>{lifecycle}</StatusPill>
      </div>
      {lifecycle === "IMPORTING" ? <p className="mt-2 text-sm text-warn-ink">{job.status === "materializing" ? "Objects are still promoting. The tenant is not active." : "Materialized and verified, but not activated. The tenant remains IMPORTING."}</p> : null}
      {lifecycle === "ACTIVE" ? <p className="mt-2 text-sm text-success-ink">Target is ACTIVE. The source cutover receipt was consumed.</p> : null}
      {lifecycle === "ABORTED" ? <p className="mt-2 text-sm text-danger">Target is ABORTED. Transfer its signed abort receipt to recover the archived source.</p> : null}
      {job.failure_detail ? <p className="mt-2 text-sm text-danger" role="alert">{job.failure_detail}</p> : null}
      <ErrorText error={detail.error} />
      <p className="mt-2 text-xs text-muted">{job.source_retention_notice}</p>
      {job.source_deployment_identity && typeof job.source_deployment_identity === "object" ? (
        <div className="mt-2"><p className="text-xs font-semibold text-ink">Archived source deployment identity</p><pre className="mt-1 overflow-auto rounded border border-line bg-bg p-2 text-xs text-muted">{JSON.stringify(job.source_deployment_identity, null, 2)}</pre></div>
      ) : null}

      {job.status === "awaiting_identity" || job.status === "ready" ? <TenantMigrationIdentityDecisions job={job} /> : null}
      {job.status === "ready" ? (
        <div className="mt-3 rounded-md border border-line bg-bg p-3">
          <h4 className="title-section">Materialize target</h4>
          <div className="mt-2 grid gap-3 md:grid-cols-2">
            <label className="text-sm text-ink">Target tenant name (optional)<input className="desk-input mt-1 w-full" value={targetName} onChange={(event) => setTargetName(event.target.value)} /></label>
            <label className="text-sm text-ink">Target tenant slug (optional)<input className="desk-input mt-1 w-full" value={targetSlug} onChange={(event) => setTargetSlug(event.target.value)} /></label>
          </div>
          <label className="mt-2 flex min-h-11 items-center gap-2 text-sm text-ink">
            <input className="h-5 w-5 accent-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus" type="checkbox" checked={reviewedIdentities} onChange={(event) => setReviewedIdentities(event.target.checked)} />
            I reviewed every per-person identity decision shown above or in its prior review record.
          </label>
          <button className="desk-button-primary mt-3" type="button" disabled={!reviewedIdentities || run.isPending} onClick={() => run.mutate()}>{run.isPending ? "Starting materialization…" : "Run reviewed import"}</button>
          <ErrorText error={run.error} field="target_identity" />
        </div>
      ) : null}

      {job.status === "completed" ? (
        <VerificationReportView report={verification.data} loading={verification.isLoading} error={verification.error} />
      ) : null}
      {job.status === "completed" && pairing && lifecycle === "IMPORTING" ? (
        <div className="mt-3 rounded-md border border-danger/40 bg-danger/5 p-3">
          <h4 className="title-section">One-way target cutover</h4>
          <p className="mt-1 text-sm text-ink">Activation and abort are mutually exclusive. Activation cannot be undone from this screen.</p>
          <label className="mt-2 block text-sm text-ink">Source cutover receipt<textarea className="desk-input mt-1 min-h-28 w-full font-mono text-xs" value={sourceReceiptText} onChange={(event) => setSourceReceiptText(event.target.value)} /></label>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="desk-button-danger" type="button" disabled={!sourceReceipt || !verification.data || activate.isPending} onClick={() => {
              if (sourceReceipt && window.confirm(`Activate ${tenantName}? This target cutover cannot be undone from this screen.`)) activate.mutate(sourceReceipt);
            }}>Activate target {tenantName}</button>
            <button className="desk-button-danger" type="button" disabled={abort.isPending} onClick={() => {
              if (window.confirm(`Abort ${tenantName}? Imported target objects will be rolled back.`)) abort.mutate();
            }}>Abort target {tenantName}</button>
          </div>
        </div>
      ) : null}
      {job.status === "completed" && !pairing ? <p className="mt-3 text-sm text-warn-ink">Pin the matching deployment pairing before cutover actions become available.</p> : null}
      <ErrorText error={activate.error ?? abort.error} field="receipt" />
      <ReceiptOutput label="Target abort receipt — transfer to source" receipt={abort.data?.receipt} />
    </article>
  );
}

function VerificationReportView({ report, loading, error }: { report?: VerificationReport; loading: boolean; error: unknown }) {
  return (
    <section className="mt-3 rounded-md border border-accent/40 bg-accent/5 p-3" aria-label="Import verification report">
      <h4 className="title-section">Verification report</h4>
      {loading ? <p className="mt-2 text-sm text-muted">Loading the persisted verification report…</p> : null}
      <ErrorText error={error} />
      {report ? <>
        <p className="mt-2 text-sm text-ink">Target makerspace {report.target_makerspace_id} · {report.identities_linked} linked · {report.identities_created} walk-ins · {report.external_references_created} external references</p>
        <div className="mt-2 grid gap-2 md:grid-cols-3">
          {(["imported", "resolved", "dropped"] as const).map((key) => <div className="rounded border border-line bg-bg p-2" key={key}><p className="eyebrow">{key}</p><pre className="mt-1 overflow-auto text-xs text-muted">{JSON.stringify(report[key], null, 2)}</pre></div>)}
        </div>
      </> : null}
    </section>
  );
}

function importRunning(job: ImportJob) {
  return job.status === "pending" || job.status === "materializing";
}
