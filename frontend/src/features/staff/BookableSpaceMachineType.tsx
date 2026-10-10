import { useQuery } from "@tanstack/react-query";
import { collectionResults, getMachineTypes, machineKeys } from "./machinesApi";

export function BookableSpaceMachineType({ makerspaceId, value, onChange }: {
  makerspaceId: number; value: number | null; onChange: (value: number | null) => void;
}) {
  const query = useQuery({ queryKey: machineKeys.types(makerspaceId), queryFn: () => getMachineTypes(makerspaceId), retry: false });
  const rows = collectionResults(query.data);
  return <label className="grid gap-1 text-sm font-semibold text-ink">Training for machine type
    <select className="desk-input" value={value ?? ""} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}>
      <option value="">No machine certification link</option>
      {value && !rows.some((row) => row.id === value) ? <option value={value}>Existing training link</option> : null}
      {rows.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
    </select>
    <span className="text-xs font-normal text-muted">When certification gating is enabled, bookings require this machine type's training.</span>
    {query.isLoading ? <span role="status" className="text-xs font-normal text-muted">Loading machine types…</span> : null}
    {query.isError ? <span className="text-xs font-normal text-muted">Machine types are unavailable. Staff with machine scope can configure the training link while Machines is enabled.</span> : null}
  </label>;
}
