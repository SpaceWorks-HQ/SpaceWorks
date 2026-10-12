import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import type { Makerspace } from "./panels/shared";

type Domain = "event" | "booking";
type Props = { makerspace: Makerspace; settings?: Makerspace; loading: boolean };

function ReminderPolicy({ makerspace, settings, loading, domain }: Props & { domain: Domain }) {
  const field = `${domain}_reminder_lead_hours` as const;
  const current = settings?.[field] ?? makerspace[field] ?? [24];
  const [draft, setDraft] = useState(current.join(", "));
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const queryClient = useQueryClient();
  useEffect(() => { if (!dirty) setDraft(current.join(", ")); }, [current, dirty]);
  const update = useMutation({
    mutationFn: (hours: number[]) => staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
      method: "PATCH", body: JSON.stringify({ [field]: hours }),
    }),
    onSuccess: async () => {
      setDirty(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] }),
        queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] }),
      ]);
    },
  });
  function save(event: React.FormEvent) {
    event.preventDefault();
    const parts = draft.trim() ? draft.split(",").map((part) => part.trim()) : [];
    const hours = parts.map(Number);
    if (parts.some((part) => !/^\d+$/.test(part)) || hours.length > 100
        || hours.some((hour) => hour < 1 || hour > 8760) || new Set(hours).size !== hours.length) {
      setError("Enter unique whole hours from 1 to 8760, separated by commas, or leave blank to disable.");
      return;
    }
    setError("");
    update.mutate(hours);
  }
  const label = domain === "event" ? "Event" : "Booking";
  return (
    <form onSubmit={save} className="grid gap-3 rounded-md border border-line bg-bg p-4">
      <h3 className="text-base font-semibold text-ink">{label} reminders</h3>
      <p className="text-sm text-muted">
        Email members before confirmed {domain === "event" ? "events" : "bookings"}, using the makerspace timezone.
        The notification matrix email setting and member opt-out still apply.
        {domain === "booking" ? " Booking requester emails must also be enabled for the space." : ""}
      </p>
      <label className="grid gap-1 text-sm text-ink">
        <span>{label} reminder lead hours</span>
        <input className="desk-input" value={draft} disabled={loading || update.isPending}
          onChange={(event) => { setDraft(event.target.value); setDirty(true); }} aria-describedby={`${domain}-reminder-help`} />
      </label>
      <p id={`${domain}-reminder-help`} className="text-sm text-muted">For example: 24, 2. Leave blank to disable.</p>
      {error || update.error ? <p role="alert" className="text-sm text-danger">{error || update.error?.message}</p> : null}
      <button className="desk-button justify-self-start" disabled={loading || update.isPending || !dirty}>
        {update.isPending ? "Saving…" : `Save ${domain} reminders`}
      </button>
      {update.isSuccess && !dirty ? <p role="status" className="text-sm text-muted">Reminder policy saved.</p> : null}
    </form>
  );
}

export function MakerspaceReminderSettings(props: Props) {
  const modules = props.settings?.enabled_modules ?? props.makerspace.enabled_modules ?? [];
  return <div className="grid gap-4">
    {modules.includes("events") ? <ReminderPolicy {...props} domain="event" /> : null}
    {modules.includes("bookings") ? <ReminderPolicy {...props} domain="booking" /> : null}
  </div>;
}
