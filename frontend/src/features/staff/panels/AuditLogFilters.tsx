import { Field } from "../../../components/ui";

export type AuditFilters = {
  makerspace: string;
  action: string;
  actor: string;
  targetType: string;
  targetId: string;
  start: string;
  end: string;
};

export const emptyAuditFilters: AuditFilters = {
  makerspace: "", action: "", actor: "", targetType: "", targetId: "", start: "", end: "",
};

// Query-string form of the filters, exactly as the audit list and the verification POST
// accept them. Dates are local calendar days: `start` inclusive at 00:00 and `end`
// exclusive at the following midnight, matching the server's [start, end) contract.
export function auditFilterParams(filters: AuditFilters): Record<string, string> {
  const params: Record<string, string> = {};
  if (filters.makerspace) params.makerspace = filters.makerspace;
  if (filters.action) params.action = filters.action;
  if (filters.actor) params.actor = filters.actor;
  if (filters.targetType) params.target_type = filters.targetType;
  if (filters.targetId) params.target_id = filters.targetId;
  if (filters.start) params.start = new Date(`${filters.start}T00:00:00`).toISOString();
  if (filters.end) {
    const end = new Date(`${filters.end}T00:00:00`);
    end.setDate(end.getDate() + 1);
    params.end = end.toISOString();
  }
  return params;
}

export function AuditLogFilters({
  filters,
  onChange,
}: {
  filters: AuditFilters;
  onChange: (next: AuditFilters) => void;
}) {
  const set = (key: keyof AuditFilters) => (event: { target: { value: string } }) =>
    onChange({ ...filters, [key]: event.target.value });
  return (
    <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      <Field label="Makerspace ID"><input className="desk-input" inputMode="numeric" value={filters.makerspace} onChange={set("makerspace")} /></Field>
      <Field label="Action"><input className="desk-input" placeholder="e.g. request.issued" value={filters.action} onChange={set("action")} /></Field>
      <Field label="Actor ID"><input className="desk-input" inputMode="numeric" value={filters.actor} onChange={set("actor")} /></Field>
      <Field label="Target type"><input className="desk-input" placeholder="e.g. inventory.inventoryproduct" value={filters.targetType} onChange={set("targetType")} /></Field>
      <Field label="Target ID"><input className="desk-input" value={filters.targetId} onChange={set("targetId")} /></Field>
      <Field label="From"><input className="desk-input" type="date" value={filters.start} onChange={set("start")} /></Field>
      <Field label="To"><input className="desk-input" type="date" value={filters.end} onChange={set("end")} /></Field>
    </div>
  );
}
