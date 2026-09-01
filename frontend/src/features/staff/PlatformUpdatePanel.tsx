import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { Panel } from "./StaffPanels";

type UpdateStatus = "idle" | "queued" | "running" | "failed";

type PlatformUpdateSettings = {
  automatic_updates_enabled: boolean;
  status: UpdateStatus;
  current_version: string;
  available_version: string;
  target_version: string;
  update_requested_at: string | null;
  last_checked_at: string | null;
  last_updated_at: string | null;
  last_backup_at: string | null;
  last_backup_name: string;
  last_error: string;
  updated_at: string;
};

const QUERY_KEY = ["platform-update-settings"];

const STATUS_COPY: Record<UpdateStatus, string> = {
  idle: "Ready",
  queued: "Update queued",
  running: "Updating",
  failed: "Update failed",
};

export function PlatformUpdatePanel() {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => staffRequest<PlatformUpdateSettings>("/admin/platform/update-settings"),
    refetchInterval: (query) =>
      query.state.data?.status === "queued" || query.state.data?.status === "running"
        ? 5_000
        : 60_000,
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) =>
      staffRequest<PlatformUpdateSettings>("/admin/platform/update-settings", {
        method: "PATCH",
        body: JSON.stringify({ automatic_updates_enabled: enabled }),
      }),
    onSuccess: (data) => queryClient.setQueryData(QUERY_KEY, data),
  });
  const updateNow = useMutation({
    mutationFn: () =>
      staffRequest<PlatformUpdateSettings>("/admin/platform/update-settings/update-now", {
        method: "POST",
      }),
    onSuccess: (data) => queryClient.setQueryData(QUERY_KEY, data),
  });

  const data = settings.data;
  const busy = toggle.isPending || updateNow.isPending;
  const updateAvailable = Boolean(
    data?.current_version &&
      data.available_version &&
      data.current_version !== data.available_version,
  );
  const mutationError = toggle.error || updateNow.error;

  return (
    <Panel title="Software updates">
      {settings.isLoading ? (
        <p className="text-sm text-muted">Loading update settings...</p>
      ) : settings.error ? (
        <p className="text-sm text-danger" role="alert">{settings.error.message}</p>
      ) : data ? (
        <div className="space-y-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-2xl">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="title-section">Automatic updates</h3>
                <span className={statusClass(data.status)}>{STATUS_COPY[data.status]}</span>
              </div>
              <p className="mt-1 text-sm text-muted">
                When enabled, the host checks every seven days and installs the newest completed main release.
                Turn it off to stop automatic installation; scheduled checks and manual updates still work.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-ink">
                {data.automatic_updates_enabled ? "On" : "Off"}
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={data.automatic_updates_enabled}
                aria-label="Automatic updates"
                className={`desk-button relative h-11 w-16 shrink-0 rounded-full p-0 ${
                  data.automatic_updates_enabled
                    ? "border-accent bg-accent disabled:hover:bg-accent"
                    : "border-outline bg-surface disabled:hover:bg-surface"
                }`}
                disabled={busy || data.status === "running"}
                onClick={() => toggle.mutate(!data.automatic_updates_enabled)}
              >
                <span
                  aria-hidden="true"
                  className={`absolute top-2 h-7 w-7 rounded-full bg-panel transition-transform duration-200 ${
                    data.automatic_updates_enabled ? "translate-x-7" : "translate-x-2"
                  }`}
                />
              </button>
            </div>
          </div>

          <dl className="grid gap-x-8 gap-y-3 border-y border-line py-4 sm:grid-cols-2">
            <VersionRow label="Installed version" value={data.current_version || "Not reported yet"} />
            <VersionRow label="Latest release" value={data.available_version || "Waiting for first check"} />
            <VersionRow label="Last checked" value={formatDate(data.last_checked_at)} />
            <VersionRow label="Last updated" value={formatDate(data.last_updated_at)} />
          </dl>

          {!data.last_checked_at ? (
            <p className="rounded-md bg-warn/15 p-3 text-sm text-warn-ink">
              The host updater has not checked in yet. Finish the automatic-update setup on the Docker host before using this control.
            </p>
          ) : null}
          {updateAvailable ? (
            <p className="text-sm font-medium text-accent-ink">
              {data.available_version} is ready to install.
            </p>
          ) : null}
          {data.last_error ? (
            <p className="rounded-md bg-danger/10 p-3 text-sm text-danger" role="alert">
              {data.last_error}
            </p>
          ) : null}

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="desk-button-primary"
              disabled={busy || data.status === "queued" || data.status === "running"}
              onClick={() => updateNow.mutate()}
            >
              {updateNow.isPending ? "Queueing..." : data.status === "queued" ? "Update queued" : data.status === "running" ? "Updating..." : "Update now"}
            </button>
            <p className="text-sm text-muted">
              The host starts a queued update at its next scheduled check, which may take up to seven days.
            </p>
          </div>

          <section aria-labelledby="backup-explainer" className="border-t border-line pt-4">
            <h3 id="backup-explainer" className="title-section">What is the update backup?</h3>
            <p className="mt-1 max-w-3xl text-sm text-muted">
              Before changing containers, Space Works saves a compressed PostgreSQL snapshot in the host&apos;s <code>backups/</code> folder. It can restore users, settings, inventory, requests, loans, and audit records if an update goes wrong. It is kept for 14 days.
            </p>
            <p className="mt-2 max-w-3xl text-sm text-muted">
              If deployment or readiness fails, the host automatically returns the application containers to the previous retained release. The database snapshot is preserved for recovery but is never restored automatically, avoiding destructive data replacement.
            </p>
            <p className="mt-2 max-w-3xl text-sm text-muted">
              Uploaded photos, evidence, documents, and print files live in MinIO and are not inside this database backup. Back up the MinIO data volume separately.
            </p>
            <p className="mt-3 text-sm text-ink">
              Latest database backup: <span className="font-mono text-xs">{data.last_backup_name || "None recorded"}</span>
              {data.last_backup_at ? ` · ${formatDate(data.last_backup_at)}` : ""}
            </p>
          </section>

          {mutationError ? <p className="text-sm text-danger" role="alert">{mutationError.message}</p> : null}
        </div>
      ) : null}
    </Panel>
  );
}

function VersionRow({ label, value }: { label: string; value: string }) {
  return <div><dt className="eyebrow">{label}</dt><dd className="mt-1 break-all font-mono text-xs text-ink">{value}</dd></div>;
}

function formatDate(value: string | null) {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function statusClass(status: UpdateStatus) {
  if (status === "failed") return "status-box status-box-danger";
  if (status === "running" || status === "queued") return "status-box status-box-pending";
  return "status-box status-box-done";
}
