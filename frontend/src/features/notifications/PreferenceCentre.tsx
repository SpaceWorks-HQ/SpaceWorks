import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { memberRequest } from "../../lib/api";
import { personalRecipientKey } from "./personalQueryKeys";

type Cell = { daily_digest?: boolean; feature: string; channel: string; enabled: boolean; available: boolean; mandatory_events: string[] };
type Preferences = { cells: Cell[] };

export function PreferenceCentre({ makerspaceId, digests = false }: { makerspaceId: number; digests?: boolean }) {
  const client = useQueryClient();
  const key = ["notifications-preferences", makerspaceId, personalRecipientKey()];
  const path = `/notifications/preferences/${makerspaceId}`;
  const preferences = useQuery({ queryKey: key, queryFn: () => memberRequest<Preferences>(path) });
  const save = useMutation({ mutationFn: async (cell: Cell & { changeDigest?: boolean }) => {
    const recipientKey = key;
    const data = await memberRequest<Preferences>(path, {
      method: "PATCH", body: JSON.stringify({ feature: cell.feature, channel: cell.channel, enabled: cell.changeDigest ? cell.enabled : !cell.enabled, ...(cell.changeDigest ? { daily_digest: !cell.daily_digest } : {}) }),
    });
    return { data, recipientKey };
  }, onSuccess: ({ data, recipientKey }) => client.setQueryData(recipientKey, data) });
  const error = preferences.error ?? save.error;
  return <section className="desk-panel p-5">
    <h2 className="title-panel">Communication preferences</h2>
    <p className="mt-2 text-sm text-muted">Choose optional messages for each family and personal channel. Safety and account recovery emails always remain enabled. Makerspace channel switches still apply.</p>
    {preferences.isLoading ? <p className="mt-3 text-sm text-muted">Loading preferences...</p> : null}
    {error ? <p className="mt-3 text-sm text-danger" role="alert">{error.message}</p> : null}
    <div className="mt-3 grid gap-3 sm:grid-cols-2">{preferences.data?.cells.map((cell) => <div key={`${cell.feature}:${cell.channel}`}
      className="flex items-start gap-2 rounded-md border border-line p-3 text-sm">
      <input type="checkbox" aria-label={`${cell.feature} ${cell.channel} messages`} checked={cell.enabled} disabled={save.isPending || (!cell.available && !cell.enabled)}
        onChange={() => save.mutate(cell)} />
      <span>{cell.feature.replace(/_/g, " ")} · {cell.channel === "in_app" ? "Inbox" : cell.channel.replace(/_/g, " ")}
        {!cell.available ? <span className="block text-xs text-muted">Disabled by makerspace</span> : null}
        {cell.mandatory_events.length ? <span className="block text-xs text-muted">Safety emails stay enabled: {cell.mandatory_events.map((event) => event.replace(/_/g, " ")).join(", ")}</span> : null}
      </span>
      {digests && cell.channel === "email" ? <label className="text-sm"><input type="checkbox" aria-label={`${cell.feature} daily digest`} checked={cell.daily_digest ?? false} disabled={save.isPending || !cell.enabled || !cell.available} onChange={() => save.mutate({ ...cell, changeDigest: true })} /> Daily digest for optional emails</label> : null}
    </div>)}</div>
  </section>;
}
