import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  issueDataExportDownload,
  listDataExports,
  requestDataExport,
  type DataExportJob,
} from "./dataExportsApi";
import { Panel } from "./panels/shared";

export function DataExportsPanel({ makerspaceId }: { makerspaceId: number }) {
  const queryClient = useQueryClient();
  const queryKey = ["data-exports", makerspaceId];
  const jobs = useQuery({
    queryKey,
    queryFn: () => listDataExports(makerspaceId),
    refetchInterval: (query) =>
      (query.state.data as DataExportJob[] | undefined)?.some(isRunning) ? 1500 : false,
  });
  const requestExport = useMutation({
    mutationFn: () => requestDataExport(makerspaceId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });
  const download = useMutation({
    mutationFn: (jobId: string) => issueDataExportDownload(makerspaceId, jobId),
    onSuccess: ({ url }) => {
      const link = document.createElement("a");
      link.href = url;
      link.rel = "noopener";
      document.body.appendChild(link);
      link.click();
      link.remove();
    },
  });
  const rows = jobs.data ?? [];

  return (
    <Panel title="Makerspace data export">
      <div className="grid gap-4">
        <div className="rounded-md border border-warn/40 bg-warn/10 p-4 text-sm text-ink">
          <p className="font-semibold">Read this disclosure before requesting an export</p>
          <p className="mt-2">
            The readable archive includes makerspace-owned records, but omits credentials,
            bearer tokens, platform configuration, selected JSON configuration, audit metadata,
            and free-text form answers. It is not a migration backup.
          </p>
          <p className="mt-2">
            <span className="font-semibold">It does contain member contact details.</span>{" "}
            Names, email addresses and phone numbers that members supplied on your records are
            included in readable form. &ldquo;Redacted&rdquo; refers to audit metadata and form
            answers, not to personal data — handle the file accordingly.
          </p>
          <p className="mt-2">
            The referenced-users file contains only id and username for people referenced by
            exported rows. This is a new intentional disclosure: the staff audit API exposes
            only a numeric actor id and the current console omits the actor. Usernames are
            identifying and can correlate a person across exports.
          </p>
        </div>

        <div>
          <button
            className="desk-button-primary"
            type="button"
            disabled={requestExport.isPending || rows.some(isRunning)}
            onClick={() => requestExport.mutate()}
          >
            {requestExport.isPending ? "Requesting…" : "Request redacted export"}
          </button>
          {requestExport.error ? <p className="mt-2 text-sm text-danger" role="alert">{requestExport.error.message}</p> : null}
        </div>

        {jobs.isLoading ? <p className="text-sm text-muted">Loading export jobs…</p> : null}
        {jobs.error ? <p className="text-sm text-danger" role="alert">{jobs.error.message}</p> : null}
        {!jobs.isLoading && rows.length === 0 ? (
          <p className="text-sm text-muted">No exports have been requested.</p>
        ) : null}
        <div className="grid gap-3">
          {rows.map((job) => (
            <ExportJobRow
              key={job.id}
              job={job}
              downloading={download.isPending && download.variables === job.id}
              onDownload={() => download.mutate(job.id)}
            />
          ))}
        </div>
        {download.error ? <p className="text-sm text-danger" role="alert">{download.error.message}</p> : null}
      </div>
    </Panel>
  );
}

function ExportJobRow({
  job,
  downloading,
  onDownload,
}: {
  job: DataExportJob;
  downloading: boolean;
  onDownload: () => void;
}) {
  const total = job.manifest.total_rows;
  return (
    <article className="rounded-md border border-line bg-bg p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-medium text-ink">Redacted export</p>
          <p className="text-xs text-muted">
            {new Date(job.created_at).toLocaleString()} · {statusLabel(job)}
            {typeof total === "number" ? ` · ${total} rows` : ""}
          </p>
        </div>
        {job.status === "available" ? (
          <button className="desk-button" type="button" disabled={downloading} onClick={onDownload}>
            {downloading ? "Preparing link…" : "Download archive"}
          </button>
        ) : null}
      </div>
      {job.status === "failed" ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {job.failure_detail || "The export failed."}
        </p>
      ) : null}
    </article>
  );
}

function isRunning(job: DataExportJob) {
  return job.status === "pending" || job.status === "running";
}

function statusLabel(job: DataExportJob) {
  if (job.status === "available") return "Ready to download";
  if (job.status === "failed") return job.failure_code === "deadline_exceeded" ? "Deadline exceeded" : "Failed";
  return job.status === "pending" ? "Queued" : "Building snapshot";
}
