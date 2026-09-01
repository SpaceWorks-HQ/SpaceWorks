import { useEffect, useMemo, useState } from "react";

import type { StaffEvent } from "./eventsApi";
import { useReplaceEventOrganizers } from "./eventsApi";
import { useOrganizations } from "./organizationsApi";

export function EventOrganizers({ event, makerspaceId, disabled }: {
  event: StaffEvent;
  makerspaceId: number;
  disabled: boolean;
}) {
  const organizations = useOrganizations();
  const [selected, setSelected] = useState<number[]>(event.organizers.map((item) => item.id));
  const replace = useReplaceEventOrganizers(makerspaceId, event.id);
  useEffect(() => setSelected(event.organizers.map((item) => item.id)), [event.organizers]);
  const assignable = organizations.data?.results ?? [];
  const assignableIds = useMemo(() => new Set(assignable.map((item) => item.id)), [assignable]);
  const retained = event.organizers.filter((item) => !assignableIds.has(item.id));

  function toggle(id: number) {
    setSelected((values) => values.includes(id) ? values.filter((item) => item !== id) : [...values, id]);
  }

  return (
    <section className="rounded-xl border border-line bg-bg p-4" aria-labelledby={`event-${event.id}-organizers`}>
      <h3 className="title-section" id={`event-${event.id}-organizers`}>Organization organizers</h3>
      <p className="mt-1 text-sm text-muted">Attribution and event-specific authority only. The host makerspace remains the owner.</p>
      {organizations.isLoading ? <p className="mt-3 text-sm text-muted">Loading organizations...</p> : null}
      {organizations.error ? <p className="mt-3 text-sm text-danger" role="alert">{organizations.error.message}</p> : null}
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {assignable.map((organization) => (
          <label className="flex items-center gap-2 rounded-lg border border-line bg-surface p-3 text-sm" key={organization.id}>
            <input type="checkbox" checked={selected.includes(organization.id)} disabled={disabled} onChange={() => toggle(organization.id)} />
            <span><span className="font-semibold text-ink">{organization.name}</span><span className="ml-1 font-mono text-xs text-muted">({organization.slug})</span></span>
          </label>
        ))}
        {retained.map((organization) => (
          <label className="flex items-center gap-2 rounded-lg border border-line bg-surface p-3 text-sm text-muted" key={organization.id}>
            <input type="checkbox" checked disabled />
            {organization.name} (retained co-organizer)
          </label>
        ))}
      </div>
      {!assignable.length && !retained.length && !organizations.isLoading ? <p className="mt-3 text-sm text-muted">No active organization memberships are available to assign.</p> : null}
      {!disabled ? <button className="desk-button-primary mt-3" type="button" disabled={replace.isPending} onClick={() => replace.mutate(selected)}>{replace.isPending ? "Saving..." : "Save organizers"}</button> : null}
      {replace.error ? <p className="mt-2 text-sm text-danger" role="alert">{replace.error.message}</p> : null}
    </section>
  );
}
