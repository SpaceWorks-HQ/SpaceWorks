import { useQuery } from "@tanstack/react-query";

import { Panel, type Makerspace } from "./panels/shared";
import { getTenantUsage, usageAmount, type TenantUsage } from "./platformMonitoringApi";

export function UsageTable({ data }: { data: TenantUsage }) {
  return <div className="overflow-x-auto"><table className="w-full text-left text-sm">
    <caption className="sr-only">Resource usage against effective limits</caption>
    <thead><tr className="border-b border-line"><th className="p-2" scope="col">Resource</th><th className="p-2" scope="col">Used</th><th className="p-2" scope="col">Limit</th><th className="p-2" scope="col">Allowance used</th></tr></thead>
    <tbody>{data.resources.map((row) => {
      const percentage = row.used !== null && row.limit !== null && row.limit > 0 ? row.used / row.limit * 100 : null;
      return <tr key={row.key} className="border-b border-line">
        <th className="p-2 font-medium capitalize" scope="row">{row.label}</th>
        <td className="p-2">{usageAmount(row.used, row.unit)}</td>
        <td className="p-2">{row.limit === null ? "Unlimited" : usageAmount(row.limit, row.unit)}</td>
        <td className="p-2">{percentage === null ? "—" : `${percentage.toFixed(1)}%`}
          {row.used !== null && row.limit !== null && row.used > row.limit ? " · Over limit" : null}
        </td>
      </tr>;
    })}</tbody>
  </table></div>;
}

export function TenantUsagePanel({ makerspace }: { makerspace: Makerspace }) {
  const query = useQuery({ queryKey: ["makerspace-usage", makerspace.id], queryFn: () => getTenantUsage(makerspace.id), refetchInterval: 60_000 });
  return <Panel title={`Usage · ${makerspace.name}`}>
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
      <p className="text-sm text-muted">Current counts and effective resource allowances. Daily and monthly counters reset with their quota period.</p>
      <button className="desk-button" disabled={query.isFetching} onClick={() => void query.refetch()}>Refresh usage</button>
    </div>
    {query.isLoading ? <p role="status">Loading usage…</p> : null}
    {query.error ? <p role="alert" className="text-danger">{query.error.message}</p> : null}
    {query.data ? <>
      {!query.data.managed ? <p className="mb-3 text-sm text-muted">This self-hosted deployment has no managed resource limits. Storage accounting is only maintained in managed mode.</p> : null}
      <UsageTable data={query.data} />
    </> : null}
  </Panel>;
}
