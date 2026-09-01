import type React from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import type { ApiPath } from "../../generated/api";
import { Badge, Metric } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import type { Makerspace } from "./StaffPanels";
import { staffTabPath } from "./staffTabs";

type HealthStatus = "ok" | "warn" | "error" | "unknown";

type SectionHealth = {
  status?: HealthStatus;
  detail?: string;
};

type IntegrationHealth = {
  status: Exclude<HealthStatus, "unknown">;
  email: SectionHealth & {
    total?: number;
    pending?: number;
    sent?: number;
    failed?: number;
    stalled?: number;
    last_failure?: {
      created_at: string;
      subject: string;
      error: string;
      stream: string;
    } | null;
  };
  deliveries_by_stream: SectionHealth & {
    hardware?: string | null;
    printing?: string | null;
  };
  smtp: SectionHealth & { configured?: boolean };
  telegram: SectionHealth & { configured?: boolean };
  worker: SectionHealth & {
    broker_configured?: boolean;
    eager?: boolean;
    last_seen?: string | null;
    stale?: boolean;
  };
};

const integrationHealthPath: ApiPath = "/api/v1/admin/makerspace/{makerspace_id}/integration-health";

export function IntegrationHealthPanel({ makerspace }: { makerspace: Makerspace }) {
  const health = useQuery({
    queryKey: ["integration-health", makerspace.id],
    queryFn: () =>
      staffRequest<IntegrationHealth>(
        integrationHealthPath
          .replace("/api/v1", "")
          .replace("{makerspace_id}", String(makerspace.id)),
      ),
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
  const data = health.data;

  return (
    <div className="min-w-0 rounded-md border border-line bg-bg p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-ink">Integration health</h3>
            <Badge tone={statusTone(data?.status ?? "unknown")}>{statusLabel(data?.status)}</Badge>
          </div>
          {health.isLoading ? <p className="mt-2 text-sm text-muted">Loading integration health...</p> : null}
          {health.error ? <p className="mt-2 text-sm text-danger">{health.error.message}</p> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Link className="desk-button" to={staffTabPath("email-logs", false, makerspace.slug)}>Email log</Link>
          <Link className="desk-button" to={staffTabPath("api", false, makerspace.slug)}>Telegram test</Link>
        </div>
      </div>

      {data ? (
        <div className="mt-4 grid gap-3 xl:grid-cols-2">
          <HealthBlock title="Email" status={data.email.status} detail={data.email.detail}>
            <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-5">
              <Metric label="Total" value={data.email.total} />
              <Metric label="Pending" value={data.email.pending} />
              <Metric label="Sent" value={data.email.sent} />
              <Metric label="Failed" value={data.email.failed} danger={(data.email.failed ?? 0) > 0} />
              <Metric label="Stalled" value={data.email.stalled} danger={(data.email.stalled ?? 0) > 0} />
            </div>
            <div className="mt-3 rounded-md border border-line bg-surface p-3 text-sm">
              {data.email.last_failure ? (
                <>
                  <p className="font-semibold text-ink">{data.email.last_failure.subject || "Last failure"}</p>
                  <p className="mt-1 text-xs text-muted">
                    {data.email.last_failure.stream || "email"} - {relativeTime(data.email.last_failure.created_at)}
                  </p>
                  <p className="mt-2 break-words text-muted">{data.email.last_failure.error || "No error detail."}</p>
                </>
              ) : (
                <p className="text-muted">No failed deliveries.</p>
              )}
            </div>
          </HealthBlock>

          <HealthBlock title="Deliveries by stream" status={data.deliveries_by_stream.status} detail={data.deliveries_by_stream.detail}>
            <div className="grid gap-2 sm:grid-cols-2">
              <StreamDelivery label="Hardware" value={data.deliveries_by_stream.hardware} />
              <StreamDelivery label="Printing" value={data.deliveries_by_stream.printing} />
            </div>
          </HealthBlock>

          <HealthBlock title="SMTP" status={data.smtp.status} detail={data.smtp.detail}>
            <ConfiguredBadge configured={data.smtp.configured} />
          </HealthBlock>

          <HealthBlock title="Telegram" status={data.telegram.status} detail={data.telegram.detail}>
            <ConfiguredBadge configured={data.telegram.configured} />
          </HealthBlock>

          <HealthBlock title="Worker" status={data.worker.status} detail={data.worker.detail} wide>
            <div className="grid gap-2 text-sm sm:grid-cols-4">
              <BooleanMetric label="Broker" value={data.worker.broker_configured} trueLabel="Configured" falseLabel="Eager only" />
              <BooleanMetric label="Eager" value={data.worker.eager} trueLabel="On" falseLabel="Off" />
              <BooleanMetric label="Stale" value={data.worker.stale} trueLabel="Yes" falseLabel="No" danger={data.worker.stale} />
              <div className="rounded-md border border-line bg-surface p-3">
                <p className="text-xs font-semibold uppercase text-muted">Last seen</p>
                <p className="mt-1 font-semibold text-ink">{data.worker.last_seen ? relativeTime(data.worker.last_seen) : "Never"}</p>
              </div>
            </div>
          </HealthBlock>
        </div>
      ) : null}
    </div>
  );
}

function HealthBlock({
  title,
  status,
  detail,
  wide,
  children,
}: {
  title: string;
  status?: HealthStatus;
  detail?: string;
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className={`min-w-0 rounded-md border border-line bg-bg p-3 ${wide ? "xl:col-span-2" : ""}`}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-semibold text-ink">{title}</h4>
        <Badge tone={statusTone(status)}>{statusLabel(status)}</Badge>
      </div>
      {detail ? <p className="mb-3 break-words text-sm text-danger">{detail}</p> : null}
      {children}
    </section>
  );
}

function BooleanMetric({
  label,
  value,
  trueLabel,
  falseLabel,
  danger = false,
}: {
  label: string;
  value?: boolean;
  trueLabel: string;
  falseLabel: string;
  danger?: boolean;
}) {
  return (
    <div className="rounded-md border border-line bg-surface p-3">
      <p className="text-xs font-semibold uppercase text-muted">{label}</p>
      <p className={`mt-1 font-semibold ${danger ? "text-danger" : "text-ink"}`}>{value ? trueLabel : falseLabel}</p>
    </div>
  );
}

function StreamDelivery({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="rounded-md border border-line bg-surface p-3 text-sm">
      <p className="font-semibold text-ink">{label}</p>
      <p className="mt-1 text-muted">{value ? relativeTime(value) : "Never sent"}</p>
    </div>
  );
}

function ConfiguredBadge({ configured }: { configured?: boolean }) {
  return <Badge tone={configured ? "success" : "neutral"}>{configured ? "Configured" : "Not configured"}</Badge>;
}

function statusTone(status?: HealthStatus) {
  if (status === "ok") return "success";
  if (status === "error") return "danger";
  if (status === "warn" || status === "unknown") return "warn";
  return "neutral";
}

function statusLabel(status?: HealthStatus) {
  if (!status) return "Unknown";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function relativeTime(value: string) {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "Unknown";
  const diffMs = timestamp - Date.now();
  const absMs = Math.abs(diffMs);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (absMs < hour) return rtf.format(Math.round(diffMs / minute), "minute");
  if (absMs < day) return rtf.format(Math.round(diffMs / hour), "hour");
  return rtf.format(Math.round(diffMs / day), "day");
}
