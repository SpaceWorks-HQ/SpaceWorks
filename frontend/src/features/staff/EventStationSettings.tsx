import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { eventKeys } from "./eventsApi";

type StationStatus = {
  configured: boolean; enabled?: boolean; public_token?: string; version?: number;
  station_url?: string; rotated_at?: string;
};
type Rotation = { pin: string; public_token: string; version: number; station_url: string };

export function EventStationSettings({ eventId }: { eventId: number }) {
  const queryClient = useQueryClient();
  const [pin, setPin] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  useEffect(() => {
    if (!pin) return undefined;
    const timeout = window.setTimeout(() => setPin(null), 60_000);
    return () => window.clearTimeout(timeout);
  }, [pin]);
  const query = useQuery({
    queryKey: eventKeys.checkinStation(eventId),
    queryFn: () => staffRequest<StationStatus>(`/admin/events/${eventId}/check-in/station/`),
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: eventKeys.checkinStation(eventId) });
  const rotate = useMutation({
    mutationFn: () => staffRequest<Rotation>(`/admin/events/${eventId}/check-in/station/rotate/`, { method: "POST", body: "{}" }),
    onSuccess: async (data) => { setPin(data.pin); await invalidate(); },
  });
  const reveal = useMutation({
    mutationFn: () => staffRequest<{ pin: string; version: number }>(`/admin/events/${eventId}/check-in/station/reveal/`, { method: "POST", body: JSON.stringify({ current_password: password }) }),
    onSuccess: (data) => { setPin(data.pin); setPassword(""); },
  });
  const disable = useMutation({
    mutationFn: () => staffRequest<StationStatus>(`/admin/events/${eventId}/check-in/station/`, { method: "DELETE" }),
    onSuccess: async () => { setPin(null); await invalidate(); },
  });
  const error = query.error || rotate.error || reveal.error || disable.error;
  return <section className="mt-3 rounded-lg border border-line bg-panel p-3" aria-labelledby="station-settings-title">
    <h4 id="station-settings-title" className="font-semibold text-ink">PIN check-in station</h4>
    <p className="mt-1 text-sm text-muted">The PIN is scoped to this event and check-in window. Rotation immediately invalidates old station sessions.</p>
    {query.data?.configured ? <div className="mt-3 grid gap-2 text-sm"><p>Status: <strong>{query.data.enabled ? "enabled" : "disabled"}</strong> · version {query.data.version}</p>{query.data.station_url ? <div className="flex flex-wrap gap-2"><a className="desk-button" href={query.data.station_url} target="_blank" rel="noreferrer">Open station</a><button className="desk-button" type="button" onClick={() => navigator.clipboard.writeText(query.data?.station_url ?? "")}>Copy URL</button></div> : null}</div> : <p className="mt-2 text-sm text-muted">No station PIN has been created.</p>}
    {pin ? <p className="mt-3 rounded-md border border-warning bg-warning-soft p-3 font-mono text-xl text-warning-ink" aria-live="polite">PIN: {pin}</p> : null}
    <div className="mt-3 flex flex-wrap gap-2"><button className="desk-button-primary" type="button" disabled={rotate.isPending} onClick={() => rotate.mutate()}>{query.data?.configured ? "Rotate PIN" : "Create PIN"}</button>{query.data?.enabled ? <button className="desk-button-danger" type="button" disabled={disable.isPending} onClick={() => disable.mutate()}>Disable</button> : null}</div>
    {query.data?.enabled ? <form className="mt-3 flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); reveal.mutate(); }}><label className="sr-only" htmlFor="station-current-password">Current password</label><input id="station-current-password" className="desk-input" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Current password" /><button className="desk-button" type="submit" disabled={!password || reveal.isPending}>Reveal PIN</button></form> : null}
    {error ? <p className="mt-2 text-sm text-danger" role="alert">{error.message}</p> : null}
  </section>;
}
