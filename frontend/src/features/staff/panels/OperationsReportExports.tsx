import { useMutation } from "@tanstack/react-query";

import { downloadStaffFile } from "../../../lib/api";
import { ReportSchedules } from "./ReportSchedules";
import { Panel } from "./shared";
import type { ReportCatalog, ReportKey } from "./operationsReportsConfig";

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
  grain: string;
  aggregate: boolean;
  makerspaceId: number;
  reportsEnabled: boolean;
}) {
  const exportReport = useMutation({
    mutationFn: ({ report, format }: { report: string; format: "csv" | "xlsx" }) =>
      downloadStaffFile(
        `${reportsBase}/${report}/export?format=${format}${dateSuffix}&grain=${encodeURIComponent(grain)}`,
        `${aggregate ? "all-makerspaces-" : ""}${report}.${format}`,
      ),
  });

  return (
    <>
      <Panel title="Exports">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {reports.map((definition) => (
            <div key={definition.key} className={`rounded-md border p-3 ${selectedReport === definition.key ? "border-accent bg-accent/10" : "border-line bg-bg"}`}>
              <h3 className="title-section">{definition.title}</h3>
              <div className="mt-3 flex gap-2">
                <button className="desk-button-ghost" type="button" disabled={exportReport.isPending} onClick={() => { onSelect(definition.key); exportReport.mutate({ report: definition.key, format: "csv" }); }}>
                  CSV
                </button>
                <button className="desk-button-ghost" type="button" disabled={exportReport.isPending} onClick={() => { onSelect(definition.key); exportReport.mutate({ report: definition.key, format: "xlsx" }); }}>
                  XLSX
                </button>
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

      {!aggregate && reportsEnabled ? <ReportSchedules makerspaceId={makerspaceId} reports={reports} /> : null}
    </>
  );
}
