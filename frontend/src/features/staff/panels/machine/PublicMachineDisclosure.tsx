import { useMutation, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../../../lib/api";
import { machineKeys } from "../../machinesApi";

export function PublicMachineDisclosure({ id, makerspaceId, fields }: { id: number; makerspaceId: number; fields: string[] }) {
  const client = useQueryClient();
  const save = useMutation({ mutationFn: (next: string[]) => staffRequest(`/admin/machines/${id}`, { method: "PATCH", body: JSON.stringify({ public_fields: next }) }),
    onSuccess: () => Promise.all([client.invalidateQueries({ queryKey: machineKeys.detail(id) }), client.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) })]) });
  return <section className="grid gap-2 rounded border border-line p-3"><h3 className="title-section">Public machine detail disclosures</h3><p className="text-sm text-muted">Requires Public machine details in makerspace features. Queue estimates show aggregate processing time. Camera and location remain private.</p>
    {([ ["training", "Show training requirement"], ["queue_eta", "Show queue length and estimate"] ] as const).map(([key, label]) => <label key={key} className="flex gap-2 text-sm"><input type="checkbox" disabled={save.isPending} checked={fields.includes(key)} onChange={event => save.mutate(event.target.checked ? [...fields, key] : fields.filter(v => v !== key))} />{label}</label>)}
    {save.error ? <p role="alert" className="text-sm text-danger">{save.error.message}</p> : null}
  </section>;
}
