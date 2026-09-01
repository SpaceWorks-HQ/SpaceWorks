import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Field, Metric, Modal } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import {
  fields,
  labelFor,
  mapRow,
  messageFor,
  parseDelimited,
  parseFileSample,
  suggestMapping,
  type BulkImportJob,
  type ImportResult,
  type Mapping,
  type RawRow,
} from "./BulkImportHelpers";
import { Panel, type Makerspace } from "./shared";

export function BulkImport({ makerspace }: { makerspace: Makerspace }) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [rawJson, setRawJson] = useState('[{"name":"New Kit","total_quantity":"1","available_quantity":"1"}]');
  const [tableText, setTableText] = useState("");
  const [headers, setHeaders] = useState<string[]>([]);
  const [sourceRows, setSourceRows] = useState<RawRow[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [mapping, setMapping] = useState<Mapping>({});
  const [mappingOpen, setMappingOpen] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const syncMutation = useMutation({
    mutationFn: ({ apply, rows }: { apply: boolean; rows: RawRow[] }) =>
      staffRequest<ImportResult>(`/admin/makerspace/${makerspace.id}/inventory/import/${apply ? "apply" : "preview"}`, {
        method: "POST",
        body: JSON.stringify({ rows }),
      }),
    onMutate: () => setJobId(null),
  });
  const jobMutation = useMutation({
    mutationFn: ({ file, mode }: { file: File; mode: "preview" | "apply" }) => {
      const body = new FormData();
      body.append("mode", mode);
      body.append("file", file);
      body.append("mapping", JSON.stringify(mapping));
      return staffRequest<BulkImportJob>(`/admin/makerspace/${makerspace.id}/inventory/import/jobs`, { method: "POST", body });
    },
    onSuccess: (job) => setJobId(job.id),
  });
  const jobQuery = useQuery({
    queryKey: ["bulk-import-job", makerspace.id, jobId],
    queryFn: () => staffRequest<BulkImportJob>(`/admin/makerspace/${makerspace.id}/inventory/import/jobs/${jobId}`),
    enabled: jobId !== null,
    refetchInterval: (query) => isRunning(query.state.data as BulkImportJob | undefined) ? 1000 : false,
  });
  const activeJob = jobQuery.data ?? jobMutation.data;
  const pending = syncMutation.isPending || jobMutation.isPending || isRunning(activeJob);
  const result = activeJob?.result && Object.keys(activeJob.result).length ? activeJob.result : syncMutation.data;
  const mappedRows = () => sourceRows.map((row) => mapRow(row, mapping));

  const submitRows = (apply: boolean, rows: RawRow[]) => {
    setError("");
    syncMutation.mutate({ apply, rows });
  };
  const startFileJob = (mode: "preview" | "apply") => {
    if (!selectedFile) {
      setError("Select a CSV, TSV, or XLSX file first.");
      return;
    }
    setError("");
    jobMutation.mutate({ file: selectedFile, mode });
  };
  const submitJson = (apply: boolean) => {
    try {
      const parsed = JSON.parse(rawJson);
      if (!Array.isArray(parsed) || parsed.some((row) => !row || typeof row !== "object" || Array.isArray(row))) {
        setError("Advanced JSON must be an array of row objects.");
        return;
      }
      submitRows(apply, parsed as RawRow[]);
    } catch {
      setError("Advanced JSON could not be parsed. Check commas, quotes, and brackets.");
    }
  };
  const loadRows = (rows: RawRow[]) => {
    if (!rows.length) {
      setError("No rows were found.");
      return;
    }
    const nextHeaders = Object.keys(rows[0]);
    setSourceRows(rows);
    setHeaders(nextHeaders);
    setMapping(suggestMapping(nextHeaders));
    setMappingOpen(true);
    setError("");
  };
  return (
    <Panel title="Bulk import">
      <div className="grid gap-4">
        <Field label="Upload CSV or XLSX" className="gap-2">
          <input
            className="desk-input"
            type="file"
            accept=".csv,.tsv,.xlsx"
            disabled={pending}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) { setSelectedFile(file); parseFileSample(file).then(loadRows).catch((exc: Error) => setError(exc.message)); }
            }}
          />
        </Field>
        <div className="grid gap-2">
          <Field label="Paste table"><textarea className="desk-input h-28 w-full text-sm" value={tableText} onChange={(e) => { setSelectedFile(null); setTableText(e.target.value); }} /></Field>
          <div className="desk-actions flex flex-wrap gap-2">
            <button className="desk-button-ghost" type="button" disabled={pending || !tableText.trim()} onClick={() => loadRows(parseDelimited(tableText))}>Map pasted table</button>
            <button className="desk-button-ghost" type="button" disabled={pending || !sourceRows.length} onClick={() => setMappingOpen(true)}>Edit mapping</button>
            <button className="desk-button-ghost" type="button" disabled={pending || !sourceRows.length} onClick={() => submitRows(false, mappedRows())}>Preview</button>
            <button className="desk-button-primary" type="button" disabled={pending || !sourceRows.length} onClick={() => submitRows(true, mappedRows())}>Apply rows</button>
            <button className="desk-button-primary" type="button" disabled={pending || !selectedFile} onClick={() => startFileJob("apply")}>Apply file job</button>
          </div>
        </div>
        <details open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}>
          <summary className="cursor-pointer text-sm font-semibold text-ink">Advanced JSON</summary>
          <Field label="JSON rows"><textarea className="desk-input mt-2 h-32 w-full font-mono text-sm" value={rawJson} onChange={(e) => setRawJson(e.target.value)} /></Field>
          <div className="desk-actions mt-2 flex flex-wrap gap-2">
            <button className="desk-button-ghost" type="button" disabled={pending} onClick={() => submitJson(false)}>Preview JSON</button>
            <button className="desk-button-primary" type="button" disabled={pending} onClick={() => submitJson(true)}>Apply JSON</button>
          </div>
        </details>
        {pending || activeJob ? <ProgressBar job={activeJob} loading={jobMutation.isPending || syncMutation.isPending} /> : null}
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        {syncMutation.error ? <p className="text-sm text-danger">{syncMutation.error.message}</p> : null}
        {jobMutation.error ? <p className="text-sm text-danger">{jobMutation.error.message}</p> : null}
        {jobQuery.error ? <p className="text-sm text-danger">{jobQuery.error.message}</p> : null}
        {activeJob?.status === "failed" ? <p className="text-sm text-danger">{activeJob.error || "Import job failed."}</p> : null}
        {result ? <ImportSummary result={result} /> : null}
      </div>
      <MappingModal open={mappingOpen} headers={headers} mapping={mapping} setMapping={setMapping} onClose={() => setMappingOpen(false)} onPreview={() => { setMappingOpen(false); submitRows(false, mappedRows()); }} />
    </Panel>
  );
}

function MappingModal({ open, headers, mapping, setMapping, onClose, onPreview }: { open: boolean; headers: string[]; mapping: Mapping; setMapping: React.Dispatch<React.SetStateAction<Mapping>>; onClose: () => void; onPreview: () => void }) {
  return (
    <Modal open={open} onClose={onClose} title="Map columns" footer={<div className="desk-actions flex flex-wrap justify-end gap-2"><button className="desk-button-ghost" type="button" onClick={onClose}>Cancel</button><button className="desk-button-primary" type="button" onClick={onPreview}>Preview</button></div>}>
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map((field) => (
          <label key={field} className="grid gap-1 text-sm">
            <span className="font-medium text-ink">{labelFor(field)}</span>
            <select className="desk-input" value={mapping[field] ?? ""} onChange={(e) => setMapping((current) => ({ ...current, [field]: e.target.value || undefined }))}>
              <option value="">Do not import</option>
              {headers.map((header) => <option key={header} value={header}>{header}</option>)}
            </select>
          </label>
        ))}
      </div>
    </Modal>
  );
}

function ProgressBar({ job, loading }: { job?: BulkImportJob; loading: boolean }) {
  const total = job?.total_rows ?? 0;
  const processed = job?.processed_rows ?? 0;
  const percent = total ? Math.min(100, Math.round((processed / total) * 100)) : 35;
  return (
    <div className="grid gap-1" role="status" aria-live="polite">
      <div className="h-2 overflow-hidden rounded-sm bg-line"><div className="h-full rounded-sm bg-accent transition-all" style={{ width: `${percent}%` }} /></div>
      <p className="text-xs text-muted">{job ? `${job.status} ${processed}/${total || "..."}` : loading ? "processing" : "ready"}</p>
    </div>
  );
}

function ImportSummary({ result }: { result: ImportResult }) {
  const errorRows = new Map((result.errors ?? []).map((item) => [item.row, item.errors]));
  const warningRows = new Map((result.warnings ?? []).map((item) => [item.row, item.warnings]));
  return (
    <div className="grid gap-3 rounded-md border border-line bg-panel p-3">
      <div className="grid gap-2 text-sm sm:grid-cols-5">
        <Metric label="Create" value={result.created ?? result.summary?.create ?? 0} />
        <Metric label="Update" value={result.updated ?? result.summary?.update ?? 0} />
        <Metric label="Errors" value={result.summary?.errors ?? result.errors?.length ?? 0} />
        <Metric label="Warnings" value={result.summary?.warnings ?? result.warnings?.length ?? 0} />
        <Metric label="Rows" value={result.summary?.total ?? result.rows?.length ?? 0} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="eyebrow"><tr><th scope="col" className="px-2 py-1">Row</th><th scope="col" className="px-2 py-1">Status</th><th scope="col" className="px-2 py-1">Name</th><th scope="col" className="px-2 py-1">Message</th></tr></thead>
          <tbody>{(result.rows ?? []).map((row) => {
            const errors = errorRows.get(row.row) ?? row.errors;
            const warnings = warningRows.get(row.row) ?? row.warnings;
            const message = errors ? messageFor(errors) : warnings ? messageFor(warnings) : "";
            return <tr key={row.row} className="border-t border-line"><td className="px-2 py-1">{row.row}</td><td className="px-2 py-1">{errors ? "error" : row.action ?? "ready"}</td><td className="px-2 py-1">{String(row.data?.name ?? "")}</td><td className={errors ? "px-2 py-1 text-danger" : "px-2 py-1 text-warn-ink"}>{message}</td></tr>;
          })}</tbody>
        </table>
      </div>
    </div>
  );
}

function isRunning(job?: BulkImportJob) {
  return job?.status === "pending" || job?.status === "running";
}
