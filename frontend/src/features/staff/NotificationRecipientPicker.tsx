import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { useScopeOptions } from "./NotificationDestinations";
import { EventRecipients } from "./NotificationRecipientEvent";
import type { RecipientRulesResponse } from "./notificationDestinationTypes";

const FEATURE_LABELS: Record<string, string> = {
  events: "Events",
  bookings: "Bookings",
  maintenance: "Maintenance",
  members: "Members",
};

const RECIPIENTS_KEY = (makerspaceId: number) =>
  ["notification-recipient-rules", makerspaceId] as const;

/** Who hears about one lifecycle event. Empty means the action-based default. */
export function NotificationRecipientPicker({
  makerspaceId,
  delegated = false,
}: {
  makerspaceId: number;
  delegated?: boolean;
}) {
  const path = `/admin/makerspace/${makerspaceId}/notification-recipient-rules`;
  const data = useQuery({
    queryKey: RECIPIENTS_KEY(makerspaceId),
    queryFn: () => staffRequest<RecipientRulesResponse>(path),
  });
  const [selected, setSelected] = useState<{ feature: string; event: string } | null>(null);
  const broadOptions = useScopeOptions(makerspaceId, !delegated);
  const options = delegated && data.data
    ? {
        machineTypes: data.data.scope_options.machine_types,
        machines: data.data.scope_options.machines,
        categories: data.data.scope_options.categories,
      }
    : broadOptions;
  const features = data.data?.features ?? [];
  const current = selected ?? (features[0]
    ? { feature: features[0].key, event: features[0].events[0] }
    : null);
  const events = features.find((item) => item.key === current?.feature)?.events ?? [];

  return (
    <section aria-labelledby="notification-recipients-heading" className="mt-6">
      <h4 id="notification-recipients-heading" className="title-section">
        Who gets notified
      </h4>
      <p className="mt-2 text-sm text-muted">
        {delegated
          ? "Pick recipients for maintenance alerts within your machine scope. Every rule must name at least one reachable machine or machine type."
          : "Pick recipients per event. Leave an event empty to notify everyone whose role covers it, which is the default. A member who has turned notifications off is never mailed, even when selected."}
      </p>

      {data.isLoading ? <p className="mt-3 text-sm text-muted">Loading…</p> : null}
      {!data.isLoading && features.length === 0 ? (
        <p className="mt-3 text-sm text-muted">
          None of the modules with selectable recipients are installed.
        </p>
      ) : null}

      {current ? (
        <>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <label className="grid gap-1 text-sm">
              <span className="eyebrow">Area</span>
              <select
                className="desk-input"
                onChange={(changed) => {
                  const feature = changed.target.value;
                  const first = features.find((item) => item.key === feature)?.events[0] ?? "";
                  setSelected({ feature, event: first });
                }}
                value={current.feature}
              >
                {features.map((feature) => (
                  <option key={feature.key} value={feature.key}>
                    {FEATURE_LABELS[feature.key] ?? feature.key}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-sm">
              <span className="eyebrow">Event</span>
              <select
                className="desk-input"
                onChange={(changed) =>
                  setSelected({ feature: current.feature, event: changed.target.value })
                }
                value={current.event}
              >
                {events.map((event) => (
                  <option key={event} value={event}>{event.replace(/_/g, " ")}</option>
                ))}
              </select>
            </label>
          </div>

          {data.data ? (
            <EventRecipients
              data={data.data}
              delegated={delegated}
              event={current.event}
              feature={current.feature}
              makerspaceId={makerspaceId}
              options={options}
              path={path}
            />
          ) : null}
        </>
      ) : null}
    </section>
  );
}
