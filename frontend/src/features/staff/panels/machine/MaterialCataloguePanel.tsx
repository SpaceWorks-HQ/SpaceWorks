import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../../../lib/api";
import { Pagination } from "../../../../components/ui/Pagination";
import { usePaginatedQuery } from "../../../../lib/usePaginatedQuery";

type Material = { id: number; name: string; colours: string[]; is_active: boolean };

export function MaterialCataloguePanel({ makerspaceId, typeId, custom, materialsEnabled, intakeEnabled }: { makerspaceId: number; typeId: number; custom: boolean; materialsEnabled: boolean; intakeEnabled: boolean }) {
  const client = useQueryClient();
  const path = `/admin/makerspaces/${makerspaceId}/machine-materials`;
  const key = ["machine-materials", makerspaceId, typeId];
  const rows = usePaginatedQuery<Material>({ key, path: `${path}?machine_type_id=${typeId}`, enabled: materialsEnabled, resetKey: `${makerspaceId}:${typeId}` });
  const [name, setName] = useState("");
  const [colours, setColours] = useState("");
  const [schema, setSchema] = useState("{}");
  const [schemaError, setSchemaError] = useState("");
  const refresh = () => client.invalidateQueries({ queryKey: key });
  const add = useMutation({ mutationFn: () => staffRequest(path, { method: "POST", body: JSON.stringify({ machine_type: typeId, name, colours: colours.split(",").map(v => v.trim()).filter(Boolean) }) }), onSuccess: () => { setName(""); refresh(); } });
  const toggle = useMutation({ mutationFn: (row: Material) => staffRequest(`${path}/${row.id}`, { method: "PATCH", body: JSON.stringify({ is_active: !row.is_active }) }), onSuccess: refresh });
  const intake = useQuery({ queryKey: ["staff-intake", makerspaceId, typeId], queryFn: () => staffRequest<{ intake_schema: unknown }>(`/admin/makerspaces/${makerspaceId}/machine-types/${typeId}/intake`), enabled: custom && intakeEnabled });
  const saveSchema = useMutation({ mutationFn: (parsed: unknown) => staffRequest(`/admin/makerspaces/${makerspaceId}/machine-types/${typeId}/intake`, { method: "PUT", body: JSON.stringify({ intake_schema: parsed }) }), onSuccess: () => client.invalidateQueries({ queryKey: ["staff-intake", makerspaceId, typeId] }) });
  return <section className="grid gap-3 rounded border border-line p-3">
    <h3 className="title-section">Material catalogue and job intake</h3>
    <p className="text-sm text-muted">Colours belong to each material. Pricing stays in the existing pricing settings.</p>
    {rows.data?.results.map(row => <div key={row.id} className="flex gap-2 text-sm"><span>{row.name}: {row.colours.join(", ")}</span><button type="button" className="desk-button-ghost" disabled={toggle.isPending} onClick={() => toggle.mutate(row)}>{row.is_active ? "Disable" : "Enable"}</button></div>)}
    {materialsEnabled ? <Pagination page={rows.page} totalPages={rows.totalPages} count={rows.count} pageSize={rows.pageSize} onChange={rows.setPage} /> : null}
    {materialsEnabled ? <form className="grid gap-2" onSubmit={event => { event.preventDefault(); add.mutate(); }}>
      <label className="grid gap-1 text-sm">Material name<input className="desk-input" required maxLength={100} value={name} onChange={event => setName(event.target.value)} /></label>
      <label className="grid gap-1 text-sm">Colours, separated by commas<input className="desk-input" required value={colours} onChange={event => setColours(event.target.value)} /></label>
      <button className="desk-button" disabled={add.isPending}>Add material</button>
    </form> : null}
    {custom && intakeEnabled ? <form className="grid gap-2" onSubmit={event => { event.preventDefault(); try { const parsed: unknown = JSON.parse(schema); setSchemaError(""); saveSchema.mutate(parsed); } catch { setSchemaError("Enter valid JSON."); } }}>
      <label className="grid gap-1 text-sm">Intake schema<textarea className="desk-input min-h-32 font-mono" value={schema} onChange={event => setSchema(event.target.value)} /></label>
      <p className="text-xs text-muted">Use version 1 with a fields array. Each field has key, label, type (text, number, integer, choice or boolean) and optional required. Choice fields need choices. Numeric fields accept min/max. Empty object disables intake. Enable Structured machine intake in features to show it publicly.</p>
      <div className="flex gap-2"><button className="desk-button" disabled={saveSchema.isPending}>Save intake schema</button><button className="desk-button-ghost" type="button" disabled={!intake.data} onClick={() => setSchema(JSON.stringify(intake.data?.intake_schema ?? {}, null, 2))}>Load saved schema</button></div>
    </form> : null}
    {schemaError ? <p role="alert">{schemaError}</p> : null}
    {[rows.error, intake.error, add.error, toggle.error, saveSchema.error].map((error, index) => error ? <p role="alert" className="text-sm text-danger" key={index}>{error.message}</p> : null)}
  </section>;
}
