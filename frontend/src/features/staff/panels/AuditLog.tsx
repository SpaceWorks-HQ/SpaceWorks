import { useState } from "react";

import { Skeleton } from "../../../components/ui";
import { AuditLogFilters, auditFilterParams, emptyAuditFilters, type AuditFilters } from "./AuditLogFilters";
import { AuditVerificationStatus } from "./AuditVerificationStatus";
import { Panel, useStaffGet } from "./shared";

type AuditLogEntry = {
  id: number;
  action: string;
  action_label: string;
  actor_display: string | null;
  target_type: string;
  target_id: string | number | null;
  meta: Record<string, unknown>;
  meta_redacted: boolean;
  created_at: string;
};

type AuditLogResponse = {
  count: number;
  next: string | null;
  previous: string | null;
  results: AuditLogEntry[];
};

export function AuditLog() {
  const [filters, setFilters] = useState<AuditFilters>(emptyAuditFilters);
  const [page, setPage] = useState(1);
  const filterParams = auditFilterParams(filters);
  const params = new URLSearchParams(filterParams);
  params.set("page", String(page));
  const query = params.toString();
  const logs = useStaffGet<AuditLogResponse>(["audit", query], `/admin/audit-logs?${query}`);

  // Any filter change resets to the first page; the old page may not exist any more.
  const updateFilters = (next: AuditFilters) => {
    setFilters(next);
    setPage(1);
  };

  return (
    <Panel title="Audit logs">
      <AuditLogFilters filters={filters} onChange={updateFilters} />
      <AuditVerificationStatus makerspaceId={filters.makerspace} params={filterParams} />
      <div className="grid gap-2 text-sm">
        {logs.error ? <p className="text-sm text-danger">{logs.error.message}</p> : null}
        {logs.isLoading ? <AuditLogSkeleton /> : null}
        {logs.data?.results?.map((log) => (
          <div key={log.id} className="rounded-md border border-line bg-surface p-2">
            <span className="font-semibold">{log.action_label}</span>
            <span className="ml-2 font-mono text-xs text-muted">{log.action}</span>
            {log.actor_display ? <span className="ml-2 text-muted">by {log.actor_display}</span> : null}
            <span className="ml-2 text-muted">{log.target_type}:{log.target_id}</span>
            <span className="ml-2 font-mono text-muted">{formatLocalDateTime(log.created_at)}</span>
            <MetaLine meta={log.meta} redacted={log.meta_redacted} />
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between gap-3 text-sm">
        <button className="desk-button-ghost" disabled={!logs.data?.previous} onClick={() => setPage((current) => Math.max(1, current - 1))}>
          Previous
        </button>
        <span className="text-muted">
          Page {page}{" \u2014 "}{logs.data?.count ?? 0} total
        </span>
        <button className="desk-button-ghost" disabled={!logs.data?.next} onClick={() => setPage((current) => current + 1)}>
          Next
        </button>
      </div>
    </Panel>
  );
}

// Only the server's projected metadata is ever rendered; there is no raw-meta field.
function MetaLine({ meta, redacted }: { meta: Record<string, unknown>; redacted: boolean }) {
  const entries = Object.entries(meta ?? {});
  if (!entries.length && !redacted) return null;
  return (
    <p className="mt-1 text-xs text-muted">
      {entries.map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`).join(" · ")}
      {redacted ? <span className="ml-1 italic">(some details withheld)</span> : null}
    </p>
  );
}

function AuditLogSkeleton() {
  return (
    <div className="grid gap-2" aria-hidden="true">
      {Array.from({ length: 5 }, (_, index) => (
        <div key={index} className="rounded-md border border-line bg-surface p-2">
          <div className="flex flex-wrap gap-3">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-56" />
            <Skeleton className="h-4 w-32" />
          </div>
        </div>
      ))}
    </div>
  );
}

function formatLocalDateTime(value: string) {
  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
