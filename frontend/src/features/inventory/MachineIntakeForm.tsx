import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { tenantPublicRequest } from "../../lib/api";

type IntakeField = { key: string; label: string; type: "text" | "number" | "integer" | "choice" | "boolean"; required?: boolean; choices?: string[]; min?: number; max?: number };
export type TypeIntake = { materials: { id: number | null; name: string; colours: string[] }[]; intake_schema: { version?: number; fields?: IntakeField[] } };

export function MachineIntakeForm({ slug, machineId, typeId }: { slug: string; machineId: number; typeId: number }) {
  const [title, setTitle] = useState("");
  const [values, setValues] = useState<Record<string, string | number | boolean>>({});
  const schema = useQuery({ queryKey: ["machine-intake", slug, typeId],
    queryFn: () => tenantPublicRequest<TypeIntake>(slug, `/public/${encodeURIComponent(slug)}/machine-types/${typeId}/intake`) });
  const submit = useMutation({ mutationFn: () => tenantPublicRequest<{ status: string }>(slug,
    `/public/${encodeURIComponent(slug)}/machine-service-requests`, { method: "POST", body: JSON.stringify({
      machine_id: machineId, title, capability_payload: schema.data?.intake_schema.version ? {
        schema_version: schema.data.intake_schema.version, values: {
          ...Object.fromEntries((schema.data.intake_schema.fields ?? []).filter(f => f.type === "boolean").map(f => [f.key, false])), ...values,
        },
      } : {},
    }) }) });
  if (schema.data && !schema.data.intake_schema.version) return null;
  return <form className="mt-3 grid gap-2" onSubmit={event => { event.preventDefault(); submit.mutate(); }}>
    <label className="grid gap-1 text-sm">Job title<input className="desk-input" required maxLength={200} value={title} onChange={event => setTitle(event.target.value)} /></label>
    {schema.data?.intake_schema.fields?.map(field => <label key={field.key} className="grid gap-1 text-sm">{field.label}
      {field.type === "choice" ? <select className="desk-input" required={field.required} value={String(values[field.key] ?? "")} onChange={event => setValues(v => { const next = { ...v }; if (event.target.value) next[field.key] = event.target.value; else delete next[field.key]; return next; })}><option value="">Choose</option>{field.choices?.map(c => <option key={c}>{c}</option>)}</select> :
        <input className="desk-input" type={field.type === "boolean" ? "checkbox" : field.type === "text" ? "text" : "number"}
          required={field.required && field.type !== "boolean"} min={field.min} max={field.max} step={field.type === "integer" ? 1 : "any"}
          checked={field.type === "boolean" ? Boolean(values[field.key]) : undefined}
          value={field.type === "boolean" ? undefined : String(values[field.key] ?? "")}
          onChange={event => setValues(v => {
            const next = { ...v };
            if (field.type !== "boolean" && event.target.value === "") delete next[field.key];
            else next[field.key] = field.type === "boolean" ? event.target.checked : field.type === "text" ? event.target.value : Number(event.target.value);
            return next;
          })} />}
    </label>)}
    {schema.isPending ? <p role="status">Loading job requirements…</p> : null}
    {schema.error || submit.error ? <p role="alert" className="text-sm text-danger">{(schema.error || submit.error)?.message}</p> : null}
    {submit.isSuccess ? <p role="status">Request submitted for review.</p> : <button className="desk-button" disabled={submit.isPending || !schema.data}>Request work</button>}
  </form>;
}
