import { useState } from "react";

import { EmptyState, SkeletonRows } from "../../../components/ui";
import {
  useOrganizationAnalytics,
  type OrganizationReportBreakdown,
  type OrganizationReportRows,
} from "../organizationAnalyticsApi";
import {
  reportDefinitions,
  type ReportKey,
} from "./operationsReportsConfig";
import { Panel, type Makerspace } from "./shared";

export function OrganizationAnalyticsPanel({ makerspaces }: { makerspaces: Makerspace[] }) {
  const [organizationValue, setOrganizationValue] = useState("");
  const [reportKey, setReportKey] = useState<ReportKey>("summary");
  const organizationId = positiveInteger(organizationValue);
  const report = useOrganizationAnalytics(organizationId, reportKey);

  return (
    <Panel title="Organization analytics">
      <p className="mb-3 text-sm text-muted">
        Compare one organization&apos;s owned makerspaces with its combined total.
      </p>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="eyebrow grid gap-1">
          <span>Organization ID</span>
          <input
            className="desk-input"
            inputMode="numeric"
            min="1"
            step="1"
            type="number"
            value={organizationValue}
            onChange={(event) => setOrganizationValue(event.target.value)}
          />
        </label>
        <label className="eyebrow grid gap-1">
          <span>Report</span>
          <select
            className="desk-input"
            value={reportKey}
            onChange={(event) => setReportKey(event.target.value as ReportKey)}
          >
            {reportDefinitions.map((definition) => (
              <option key={definition.key} value={definition.key}>
                {definition.title}
              </option>
            ))}
          </select>
        </label>
      </div>

      {organizationId === null ? (
        <EmptyState
          title="Select an organization"
          description="Enter the organization ID to load its authorized analytics."
        />
      ) : null}
      {report.isLoading ? <OrganizationAnalyticsSkeleton /> : null}
      {report.error ? (
        <EmptyState
          title="Unable to load organization analytics"
          description={report.error instanceof Error ? report.error.message : "Something went wrong."}
          action={(
            <button className="desk-button" type="button" onClick={() => report.refetch()}>
              Retry
            </button>
          )}
        />
      ) : null}
      {!report.isLoading && !report.error && report.data?.breakdown.length === 0 ? (
        <EmptyState
          title="No makerspaces in this organization"
          description="This organization does not currently own any reportable makerspaces."
        />
      ) : null}

      {report.data?.breakdown.length ? (
        <div className="space-y-6">
          <section aria-labelledby="organization-breakdown-heading">
            <h3 className="title-section" id="organization-breakdown-heading">Breakdown by makerspace</h3>
            <div className="mt-3 space-y-4">
              {report.data.breakdown.map((entry) => (
                <MakerspaceBreakdown
                  key={entry.makerspace_id}
                  entry={entry}
                  name={makerspaceName(entry.makerspace_id, makerspaces)}
                />
              ))}
            </div>
          </section>
          <section aria-labelledby="organization-total-heading">
            <h3 className="title-section" id="organization-total-heading">Organization total</h3>
            <AnalyticsRowsTable rows={report.data.total.rows} caption="Organization total" />
          </section>
        </div>
      ) : null}
    </Panel>
  );
}

function MakerspaceBreakdown({
  entry,
  name,
}: {
  entry: OrganizationReportBreakdown;
  name: string;
}) {
  return (
    <section aria-labelledby={`makerspace-${entry.makerspace_id}-heading`}>
      <h4 className="eyebrow" id={`makerspace-${entry.makerspace_id}-heading`}>{name}</h4>
      <AnalyticsRowsTable rows={entry.rows} caption={`${name} report`} />
    </section>
  );
}

function AnalyticsRowsTable({
  rows,
  caption,
}: {
  rows: OrganizationReportRows["rows"];
  caption: string;
}) {
  const headers = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  if (!rows.length || !headers.length) return <p className="mt-2 text-sm text-muted">No records.</p>;

  return (
    <div className="mt-2 max-h-80 overflow-auto rounded-md border border-line">
      <table className="w-full divide-y divide-line text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="eyebrow sticky top-0 bg-surface">
          <tr>
            {headers.map((header) => (
              <th scope="col" className="whitespace-nowrap px-3 py-2" key={header}>{header.replace(/_/g, " ")}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line bg-bg text-ink">
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {headers.map((header) => (
                <td className="whitespace-nowrap px-3 py-2 font-mono text-sm" key={header}>
                  {formatCell(row[header])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OrganizationAnalyticsSkeleton() {
  return (
    <div className="overflow-x-auto rounded-md border border-line" aria-label="Loading organization analytics">
      <table className="w-full divide-y divide-line text-left text-sm">
        <tbody className="divide-y divide-line bg-bg">
          <SkeletonRows rows={4} cols={4} />
        </tbody>
      </table>
    </div>
  );
}

function positiveInteger(value: string) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

function makerspaceName(id: number, makerspaces: Makerspace[]) {
  return makerspaces.find((makerspace) => makerspace.id === id)?.name ?? `Makerspace #${id}`;
}

function formatCell(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
