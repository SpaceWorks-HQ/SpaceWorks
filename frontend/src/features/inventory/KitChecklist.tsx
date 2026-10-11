import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { staffRequest } from "../../lib/api";

export type KitComponent = { key: string; label: string; quantity: number };
export type KitExpectation = KitComponent & { owner_label: string; issue_present?: number };
export type KitCount = { key: string; present: number };
export type KitPreview = { components: KitExpectation[] };

export function useKitChecklist(path: string, body: object, enabled = true,
  requestPreview: (path: string, body: object) => Promise<KitPreview> = staffPreview) {
  const token = path + JSON.stringify(body);
  const [capture, setCapture] = useState<{ token: string; values: Record<string, string> }>({ token: "", values: {} });
  useEffect(() => {
    setCapture({ token, values: {} });
  }, [token, enabled]);
  const query = useQuery({
    queryKey: ["kit-checklist-preview", path, token], enabled,
    queryFn: () => requestPreview(path, body), staleTime: 0,
  });
  const components = enabled ? query.data?.components ?? [] : [];
  const values = capture.token === token ? capture.values : {};
  const valid = components.every((row) => values[row.key]?.trim() !== "" &&
    values[row.key] !== undefined && Number.isInteger(Number(values[row.key])) &&
    Number(values[row.key]) >= 0 && Number(values[row.key]) <= row.quantity);
  return {
    components, values, counts: components.map((row) => ({ key: row.key, present: Number(values[row.key]) })),
    ready: !enabled || (query.isSuccess && !query.isFetching && valid),
    loading: enabled && query.isFetching, error: enabled ? query.error?.message : undefined,
    update: (key: string, value: string) => setCapture((current) => ({
      token, values: { ...(current.token === token ? current.values : {}), [key]: value },
    })),
  };
}

function staffPreview(path: string, body: object) {
  return staffRequest<KitPreview>(path, { method: "POST", body: JSON.stringify(body) });
}

export function useSuppliedKitChecklist(components: KitExpectation[], token: string) {
  const [capture, setCapture] = useState<{ token: string; values: Record<string, string> }>({ token: "", values: {} });
  useEffect(() => { setCapture({ token, values: {} }); }, [token]);
  const values = capture.token === token ? capture.values : {};
  return { components, values, loading: false, error: undefined,
    ready: components.every((row) => values[row.key] !== undefined && values[row.key].trim() !== "" &&
      Number.isInteger(Number(values[row.key])) && Number(values[row.key]) >= 0 && Number(values[row.key]) <= row.quantity),
    counts: components.map((row) => ({ key: row.key, present: Number(values[row.key]) })),
    update: (key: string, value: string) => setCapture((current) => ({
      token, values: { ...(current.token === token ? current.values : {}), [key]: value },
    })),
  };
}

export function KitChecklistCapture({ checklist }: { checklist: Pick<ReturnType<typeof useKitChecklist>, "components" | "values" | "loading" | "error" | "update"> }) {
  return <div className="grid gap-2">
    {checklist.loading ? <p role="status" className="text-sm text-muted">Loading kit checklist...</p> : null}
    {checklist.error ? <p role="alert" className="text-sm text-danger">{checklist.error}</p> : null}
    {checklist.components.length ? <fieldset className="grid gap-2 rounded-md border border-line p-3">
      <legend className="text-sm font-medium text-ink">Kit component counts</legend>
      <p className="text-xs text-muted">Count what is physically present. Enter 0 for a missing component.</p>
      {checklist.components.map((row) => <label key={row.key} className="grid gap-1 text-sm">
        <span>{row.owner_label}: {row.label} ({row.quantity} expected{row.issue_present !== undefined ? `, ${row.issue_present} at issue` : ""})</span>
        <input className="desk-input" type="number" required min="0" max={row.quantity} step="1"
          value={checklist.values[row.key] ?? ""} onChange={(event) => checklist.update(row.key, event.target.value)} />
      </label>)}
    </fieldset> : null}
  </div>;
}

export function KitDefinitionEditor({ value, onChange }: { value: KitComponent[]; onChange: (value: KitComponent[]) => void }) {
  return <fieldset className="grid gap-2 rounded-md border border-line p-3">
    <legend className="text-sm font-medium text-ink">Kit components</legend>
    {value.map((row) => <div key={row.key} className="grid gap-2 sm:grid-cols-[1fr_6rem_auto]">
      <label className="grid gap-1 text-sm">Component name<input className="desk-input" maxLength={200} value={row.label}
        onChange={(event) => onChange(value.map((entry) => entry.key === row.key ? { ...entry, label: event.target.value } : entry))} /></label>
      <label className="grid gap-1 text-sm">Quantity<input className="desk-input" type="number" min="1" max="999" step="1" value={row.quantity}
        onChange={(event) => onChange(value.map((entry) => entry.key === row.key ? { ...entry, quantity: Number(event.target.value) } : entry))} /></label>
      <button className="desk-button-danger self-end" type="button" onClick={() => onChange(value.filter((entry) => entry.key !== row.key))}>Remove</button>
    </div>)}
    <button className="desk-button-ghost" type="button" disabled={value.length >= 50}
      onClick={() => onChange([...value, { key: crypto.randomUUID(), label: "", quantity: 1 }])}>Add component</button>
  </fieldset>;
}
