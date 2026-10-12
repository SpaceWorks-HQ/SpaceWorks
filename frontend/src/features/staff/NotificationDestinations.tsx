import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { type NotificationDestination } from "./notificationDestinationTypes";
import { CHANNELS, DESTINATIONS_KEY } from "./notificationDestinations/channels";
import { DestinationForm } from "./notificationDestinations/DestinationForm";
import { DestinationRow } from "./notificationDestinations/DestinationRow";
import { useScopeOptions } from "./notificationDestinations/scopeOptions";

export { DESTINATIONS_KEY } from "./notificationDestinations/channels";
export { ScopePicker } from "./notificationDestinations/ScopePicker";
export { useScopeOptions } from "./notificationDestinations/scopeOptions";

/**
 * Rooms a makerspace posts alerts into.
 *
 * Console parity is mandatory here rather than nice to have: `/control/` is not proxied
 * on the public frontend port, so without this panel a space manager has no way to add a
 * room, change its webhook, or scope it to a machine.
 */
export function NotificationDestinations({
  makerspaceId,
  availableChannels,
}: {
  makerspaceId: number;
  /** Channels whose module is installed. A room on an uninstalled channel would accept
   *  the credential and then skip every send, so those options are omitted entirely. */
  availableChannels: string[];
}) {
  const queryClient = useQueryClient();
  const basePath = `/admin/makerspace/${makerspaceId}/notification-destinations`;
  const [creating, setCreating] = useState(false);

  const destinations = useQuery({
    queryKey: DESTINATIONS_KEY(makerspaceId),
    queryFn: () => staffRequest<NotificationDestination[]>(basePath),
  });
  const options = useScopeOptions(makerspaceId);

  const remove = useMutation({
    mutationFn: (id: number) => staffRequest(`${basePath}/${id}`, { method: "DELETE" }),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: DESTINATIONS_KEY(makerspaceId) }),
  });

  const usable = CHANNELS.filter((channel) => availableChannels.includes(channel.key));

  return (
    <section aria-labelledby="notification-destinations-heading" className="mt-6">
      <h4 id="notification-destinations-heading" className="text-sm font-semibold text-ink">
        Rooms
      </h4>
      <p className="mt-2 text-sm text-muted">
        Each room is one chat destination. A room with no machines or categories selected
        receives everything; narrow it to send laser faults to the laser team and printer
        faults to the print room. Webhook URLs are stored encrypted and never shown again.
      </p>

      {destinations.isLoading ? (
        <p className="mt-3 text-sm text-muted">Loading rooms…</p>
      ) : null}

      <ul className="mt-3 grid gap-2">
        {(destinations.data ?? []).map((destination) => (
          <li key={destination.id}>
            <DestinationRow
              basePath={basePath}
              destination={destination}
              makerspaceId={makerspaceId}
              onDelete={() => remove.mutate(destination.id)}
              options={options}
            />
          </li>
        ))}
      </ul>

      {destinations.data?.length === 0 && !destinations.isLoading ? (
        <p className="mt-3 text-sm text-muted">
          No rooms yet. Alerts still go to the webhook saved in Chat webhooks above until
          you add one.
        </p>
      ) : null}

      {creating ? (
        <DestinationForm
          basePath={basePath}
          channels={usable}
          makerspaceId={makerspaceId}
          onDone={() => setCreating(false)}
          options={options}
        />
      ) : (
        <button
          className="desk-button-primary mt-3"
          disabled={usable.length === 0}
          onClick={() => setCreating(true)}
          type="button"
        >
          Add a room
        </button>
      )}
      {usable.length === 0 ? (
        <p className="mt-2 text-sm text-muted">
          No chat modules are installed for this makerspace.
        </p>
      ) : null}
    </section>
  );
}
