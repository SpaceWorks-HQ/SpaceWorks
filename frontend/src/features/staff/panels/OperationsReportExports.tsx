import { useMutation } from "@tanstack/react-query";

import { downloadStaffFile } from "../../../lib/api";
import { ReportSchedules } from "./ReportSchedules";
import { Panel } from "./shared";
import { reportFormats, reportGrain, type ReportCatalog, type ReportKey } from "./operationsReportsConfig";

type ReportEntry = ReportCatalog["results"][number];

// The export/schedule block of the reports tab, split out of OperationsReports.tsx so
// that file stays under the size ceiling. It owns the export mutation (a file download,
// not server state, so nothing is invalidated) and hands schedules their definitions.
export function OperationsReportExports({
  reports,
  selectedReport,
  onSelect,
  reportsBase,
  dateSuffix,
  filters = {},
  grain,
  aggregate,
  makerspaceId,
  reportsEnabled,
}: {
  reports: ReportEntry[];
  selectedReport: ReportKey;
  onSelect: (key: ReportKey) => void;
  reportsBase: string;
  dateSuffix: string;
  filters?: { months?: string; status?: string; subject_type?: string };
  grain: string;
  aggregate: boolean;
  makerspaceId: number;
  reportsEnabled: boolean;
}) {
  const exportReport = useMutation({
    mutationFn: ({ report, format }: { report: string; format: "csv" | "xlsx" }) => {
      const exportGrain = reportGrain(reports.find((definition) => definition.key === report), grain);
      const params = new URLSearchParams();
      if (report === "member-retention" && filters.months) params.set("months", filters.months);
      if (report === "payment-reconciliation") {
        if (filters.status) params.set("status", filters.status);
        if (filters.subject_type) params.set("subject_type", filters.subject_type);
      }
      return downloadStaffFile(
        `${reportsBase}/${report}/export?format=${format}${dateSuffix}&grain=${encodeURIComponent(exportGrain)}${params.size ? `&${params}` : ""}`,
        `${aggregate ? "all-makerspaces-" : ""}${report}.${format}`,
      );
    },
  });

  return (
    <>
      <Panel title="Exports">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {reports.map((definition) => (
            <div key={definition.key} className={`rounded-md border p-3 ${selectedReport === definition.key ? "border-accent bg-accent/10" : "border-line bg-bg"}`}>
              <h3 className="title-section">{definition.title}</h3>
              <div className="mt-3 flex gap-2">
                {reportFormats(definition).map((format) => (
                  <button key={format} className="desk-button-ghost" type="button" disabled={exportReport.isPending} onClick={() => { onSelect(definition.key); exportReport.mutate({ report: definition.key, format }); }}>
                    {format.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
        {exportReport.error ? (
          <p className="mt-3 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            {exportReport.error instanceof Error ? exportReport.error.message : "Could not export report."}
          </p>
        ) : null}
      </Panel>

      {/* Only schedulable definitions reach schedules: email/chat delivery of e.g. the
          audit trail would broaden custody of accountability data. */}
      {!aggregate && reportsEnabled ? (
        <ReportSchedules makerspaceId={makerspaceId} reports={reports.filter((report) => report.schedulable !== false)} />
      ) : null}
    </>
  );
}
