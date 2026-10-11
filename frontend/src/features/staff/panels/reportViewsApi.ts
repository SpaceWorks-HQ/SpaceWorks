import { staffRequest } from "../../../lib/api";

export type ReportViewState = {
  report_key: string;
  filters: { start?: string; end?: string; months?: number; status?: string; subject_type?: string };
  grain: string;
  columns: string[];
};
export type ServerReportView = {
  id: number; makerspace: number; owner: number; name: string; state: ReportViewState; shared: boolean;
};
export type ReportViewPage = { count: number; next: string | null; previous: string | null; results: ServerReportView[] };
const base = (id: number) => `/admin/makerspaces/${id}/saved-report-views`;

export function listReportViews(id: number, page = 1) {
  return staffRequest<ReportViewPage>(`${base(id)}?page=${page}`);
}
export function getReportView(id: number, pk: number) {
  return staffRequest<ServerReportView>(`${base(id)}/${pk}`);
}
export function saveReportView(id: number, name: string, state: ReportViewState, shared: boolean) {
  return staffRequest<ServerReportView>(base(id), { method: "POST", body: JSON.stringify({ name, state, shared }) });
}
export function deleteReportView(id: number, pk: number) {
  return staffRequest<void>(`${base(id)}/${pk}`, { method: "DELETE" });
}
