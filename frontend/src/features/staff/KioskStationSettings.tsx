import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { type Makerspace, useStaffGet } from "./StaffPanels";

type KioskStation = {
  id: number;
  name: string;
  kind: "scanner" | "handover";
  enabled: boolean;
  public_token: string | null;
  version: number | null;
  station_url: string | null;
  pin?: string;
};

// Phase 9b kiosk Station administration. A freshly created or rotated PIN is shown once
// from the mutation result and never cached; the list query never carries a PIN.
export function KioskStationSettings({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const key = ["kiosk-stations", makerspace.id];
  const stations = useStaffGet<KioskStation[]>(key, `/admin/makerspace/${makerspace.id}/kiosk-stations/`);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<KioskStation["kind"]>("handover");
  const [secret, setSecret] = useState<KioskStation | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });

  const create = useMutation({
    mutationFn: () => staffRequest<KioskStation>(`/admin/makerspace/${makerspace.id}/kiosk-stations/`, {
      method: "POST", body: JSON.stringify({ name, kind }),
    }),
    onSuccess: (station) => { setSecret(station); setName(""); refresh(); },
  });
  const rotate = useMutation({
    mutationFn: (id: number) => staffRequest<KioskStation>(`/admin/kiosk-stations/${id}/rotate/`, { method: "POST" }),
    onSuccess: (station) => { setSecret(station); refresh(); },
  });
  const disable = useMutation({
    mutationFn: (id: number) => staffRequest<KioskStation>(`/admin/kiosk-stations/${id}/`, { method: "DELETE" }),
    onSuccess: () => { setSecret(null); refresh(); },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return <div className="rounded-md border border-line bg-bg p-4">
    <div className="grid max-w-2xl gap-2">
      <h3 className="text-base font-semibold text-ink">Kiosk stations</h3>
      <p className="text-sm text-muted">A Station PIN only unlocks the kiosk. Every handover still needs a signed-in staff operator, and is recorded against that person.</p>
    </div>
    <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={submit}>
      <label className="grid gap-1 text-sm">Name<input className="desk-input" required maxLength={160} value={name} onChange={(event) => setName(event.target.value)} /></label>
      <label className="grid gap-1 text-sm">Kind<select className="desk-input" value={kind} onChange={(event) => setKind(event.target.value as KioskStation["kind"])}>
        <option value="handover">Handover</option>
        <option value="scanner">Scanner</option>
      </select></label>
      <button className="desk-button-primary" type="submit" disabled={create.isPending || !name.trim()}>Create station</button>
    </form>
    {create.isError ? <p className="mt-2 text-sm text-danger" role="alert">The station could not be created.</p> : null}
    {secret?.pin ? <div className="mt-4 rounded-md border border-line p-3" role="status">
      <p className="text-sm">PIN for <strong>{secret.name}</strong> (shown once): <span className="font-mono text-lg tracking-widest">{secret.pin}</span></p>
      {secret.station_url ? <p className="mt-1 break-all font-mono text-xs text-muted">{secret.station_url}</p> : null}
    </div> : null}
    <ul className="mt-4 grid gap-2">
      {(stations.data ?? []).map((station) => <li key={station.id} className="flex flex-wrap items-center gap-3 text-sm">
        <span className="font-semibold">{station.name}</span>
        <Badge tone="neutral">{station.kind}</Badge>
        <Badge tone={station.enabled ? "success" : "warn"}>{station.enabled ? "enabled" : "disabled"}</Badge>
        <button className="desk-button-secondary" type="button" onClick={() => rotate.mutate(station.id)}>{station.enabled ? "Rotate PIN" : "Re-enable with new PIN"}</button>
        {station.enabled ? <button className="desk-button-danger" type="button" onClick={() => disable.mutate(station.id)}>Disable</button> : null}
      </li>)}
    </ul>
  </div>;
}
