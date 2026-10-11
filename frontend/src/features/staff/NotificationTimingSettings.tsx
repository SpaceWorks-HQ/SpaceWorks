import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../lib/api";

type Policy = { quiet_start: string; quiet_end: string; digest_at: string; channels: string[]; bounce_configured: boolean };
const channels = ["email", "telegram", "slack", "mattermost", "discord", "native_push", "webhook"];

export function NotificationTimingSettings({ makerspaceId, timezone }: { makerspaceId: number; timezone?: string }) {
  const client = useQueryClient();
  const key = ["notification-timing", makerspaceId];
  const path = `/integrations/makerspace/${makerspaceId}/timing-policy`;
  const policy = useQuery({ queryKey: key, queryFn: () => staffRequest<Policy>(path) });
  const [draft, setDraft] = useState<Policy | null>(null);
  const [secret, setSecret] = useState("");
  const values = draft ?? policy.data;
  const save = useMutation({ mutationFn: () => staffRequest<Policy>(path, { method: "PATCH", body: JSON.stringify({
    quiet_start: values?.quiet_start, quiet_end: values?.quiet_end, digest_at: values?.digest_at, channels: values?.channels,
    ...(secret ? { bounce_secret: secret } : {}),
  }) }), onSuccess: (data) => { client.setQueryData(key, data); setDraft(null); setSecret(""); } });
  return <form className="grid gap-3 rounded-lg border border-line p-4" onSubmit={(event) => { event.preventDefault(); save.mutate(); }} aria-label="Notification delivery times">
    <h3 className="title-section">Notification delivery times</h3>
    <p className="text-sm text-muted">Times use {timezone ?? "the makerspace timezone"}. Enable quiet hours and digests in Features. Safety alerts remain immediate; members opt into daily digests in their preferences.</p>
    {values ? <fieldset className="grid gap-3 sm:grid-cols-3" disabled={save.isPending}>
      {(["quiet_start", "quiet_end", "digest_at"] as const).map((name) => <label key={name} className="grid gap-1 text-sm">{name === "quiet_start" ? "Quiet from" : name === "quiet_end" ? "Quiet until" : "Daily digest at"}<input className="desk-input" type="time" required value={values[name].slice(0, 5)} onChange={(event) => setDraft({ ...values, [name]: event.target.value })} /></label>)}
      <div className="flex flex-wrap gap-3 sm:col-span-3">{channels.map((channel) => <label key={channel} className="flex gap-2 text-sm"><input type="checkbox" checked={values.channels.includes(channel)} onChange={(event) => setDraft({ ...values, channels: event.target.checked ? [...values.channels, channel] : values.channels.filter((item) => item !== channel) })} />{channel.replace(/_/g, " ")}</label>)}</div>
      <label className="grid gap-1 text-sm sm:col-span-3">Inbound bounce signing secret<input type="password" className="desk-input" autoComplete="new-password" minLength={32} maxLength={200} value={secret} onChange={(event) => setSecret(event.target.value)} /><span className="text-xs text-muted">{values.bounce_configured ? "Configured. Leave blank to keep it; enter a new secret to rotate." : "Use at least 32 characters. Configure the same secret in your provider adapter."}</span></label>
    </fieldset> : <p role="status">Loading delivery times…</p>}
    {policy.error || save.error ? <p role="alert" className="text-danger">{(save.error ?? policy.error)?.message}</p> : null}
    <button className="desk-button-primary w-fit" disabled={!values || save.isPending}>Save delivery times</button>
    {save.isSuccess ? <p role="status">Delivery policy saved.</p> : null}
  </form>;
}
