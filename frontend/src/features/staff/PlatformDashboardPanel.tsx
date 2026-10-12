import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Badge } from "../../components/ui";
import { Panel } from "./panels/shared";
import { getPlatformDashboard, getPlatformProblems, monitoringDate, usageAmount } from "./platformMonitoringApi";
import { UsageTable } from "./TenantUsagePanel";

export function PlatformDashboardPanel() {
  const dashboard = useQuery({ queryKey: ["platform-dashboard"], queryFn: getPlatformDashboard, refetchInterval: 60_000 });
  const problems = useQuery({ queryKey: ["platform-problems"], queryFn: getPlatformProblems, refetchInterval: 60_000 });
  const data = dashboard.data;
  return <div className="space-y-4">
    <Panel title="Platform dashboard">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">Hidden tenants are excluded. Usage totals cover live, available tenants.</p>
        <button className="desk-button" disabled={dashboard.isFetching || problems.isFetching} onClick={() => { void dashboard.refetch(); void problems.refetch(); }}>Refresh dashboard and checks</button>
      </div>
      {dashboard.isLoading ? <p role="status">Loading platform dashboard…</p> : null}
      {dashboard.error ? <p role="alert" className="text-danger">{dashboard.error.message}</p> : null}
      {data ? <>
        <p className="mb-3 text-sm text-muted">Checked {monitoringDate(data.checked_at)}</p>
        <dl className="grid gap-3 sm:grid-cols-3">{Object.entries(data.tenants_by_state).map(([state, count]) => <div key={state} className="rounded-md border border-line p-3"><dt className="capitalize text-muted">{state} tenants</dt><dd className="text-xl font-semibold">{count}</dd></div>)}</dl>
        <div className="my-4 grid gap-4 md:grid-cols-2">
          <div><h3 className="font-semibold">Backup and offsite</h3><p>Last backup result: {data.backup.status}</p><p>Last success: {monitoringDate(data.backup.last_success_at)}</p><p>Automatic backups: {data.backup.automatic_enabled ? "On" : "Off"}</p>
            {data.offsite.length ? data.offsite.map((row) => <p key={row.name}>{row.name}: {row.state.replace(/_/g, " ")} {row.has_error ? "· Needs attention" : ""} · {monitoringDate(row.verified_at)}</p>) : <p>No offsite destinations configured.</p>}
            <Link className="text-brand underline" to="/admin/backup-restore">Backup settings</Link>
          </div>
          <div><h3 className="font-semibold">Updates and delivery</h3><p>Failed emails: {data.failed_deliveries.email}</p><p>Failed notifications: {data.failed_deliveries.notifications}</p>
            {data.updates ? <><p>Update state: {data.updates.status}{data.updates.pending ? " · Pending update" : ""}</p><p>Current: {data.updates.current_version || "Unknown"}</p><p>Available: {data.updates.available_version || "Unknown"}</p></> : <p>In-app updater disabled.</p>}
            <Link className="text-brand underline" to="/admin/platform">Platform settings</Link>
          </div>
        </div>
        <details><summary className="cursor-pointer font-semibold">Usage totals</summary><dl className="mt-3 grid gap-2 sm:grid-cols-3">{Object.entries(data.usage_totals).map(([key, value]) => <div key={key}><dt className="capitalize text-muted">{key.replace(/_/g, " ")}</dt><dd>{usageAmount(value, key === "storage" ? "bytes" : "count")}</dd></div>)}</dl></details>
      </> : null}
    </Panel>
    <Panel title="Problems">
      {problems.isLoading ? <p role="status">Running checks…</p> : null}
      {problems.error ? <p role="alert" className="text-danger">{problems.error.message}</p> : null}
      {problems.data ? <>
        <p className="mb-3 text-sm text-muted">Checked {monitoringDate(problems.data.checked_at)}. Checks also run every 15 minutes through the platform scheduler.</p>
        <ul className="space-y-2">{problems.data.results.map((row, index) => <li key={`${row.key}:${row.makerspace_id}:${index}`} className="flex flex-wrap items-center gap-2 rounded-md border border-line p-3">
          <Badge tone={row.status === "error" ? "danger" : row.status === "warn" ? "warn" : "success"}>{row.status}</Badge>
          <span className="min-w-0 flex-1">{row.message}</span>
          {row.fix_url.startsWith("/control/") ? <a className="text-brand underline" href={row.fix_url}>Inspect</a> : <Link className="text-brand underline" to={row.fix_url}>Inspect</Link>}
        </li>)}</ul>
      </> : null}
    </Panel>
    {data ? <>
      <section id="scheduler"><Panel title="Scheduler freshness"><p className="mb-3 text-sm text-muted">For missing executions, check the host's beat and worker services, or its scheduled cron runner. For failed executions, inspect worker logs. Freshness records show beat completions and cron attempts.</p><div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Periodic task freshness</caption><thead><tr><th scope="col" className="p-2">Task</th><th scope="col" className="p-2">Cadence</th><th scope="col" className="p-2">Last execution</th><th scope="col" className="p-2">Status</th></tr></thead><tbody>{data.scheduler.map((task) => <tr key={task.name} className="border-t border-line"><th scope="row" className="p-2 font-medium">{task.name}</th><td className="p-2">{task.cadence_minutes} minutes</td><td className="p-2">{monitoringDate(task.last_run_at)}</td><td className="p-2">{task.status}</td></tr>)}</tbody></table></div></Panel></section>
      <Panel title="Tenant usage">{data.tenants.map((tenant) => <details key={tenant.id} className="mb-3 rounded-md border border-line p-3"><summary className="cursor-pointer font-semibold">{tenant.name}</summary><Link className="my-2 inline-block text-brand underline" to={`/m/${tenant.slug}/admin/usage`}>Open usage page</Link><UsageTable data={tenant.usage} /></details>)}</Panel>
    </> : null}
  </div>;
}
