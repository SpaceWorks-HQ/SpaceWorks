import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import {
  type NotificationDestination,
  type DestinationScope,
  EMPTY_SCOPE,
} from "./notificationDestinationTypes";

type ScopeOption = { id: number; name: string };

type ScopeOptions = {
  machineTypes: ScopeOption[];
  machines: ScopeOption[];
  categories: ScopeOption[];
};

const CHANNELS = [
  { key: "slack", label: "Slack" },
  { key: "mattermost", label: "Mattermost" },
  { key: "discord", label: "Discord" },
  { key: "telegram", label: "Telegram" },
] as const;

export const DESTINATIONS_KEY = (makerspaceId: number) =>
  ["notification-destinations", makerspaceId] as const;

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
          className="desk-btn mt-3"
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

function DestinationRow({
  basePath,
  destination,
  makerspaceId,
  onDelete,
  options,
}: {
  basePath: string;
  destination: NotificationDestination;
  makerspaceId: number;
  onDelete: () => void;
  options: ScopeOptions;
}) {
  const [editing, setEditing] = useState(false);
  const scopeCount =
    destination.scope.machine_ids.length +
    destination.scope.machine_type_ids.length +
    destination.scope.category_ids.length;

  if (editing) {
    return (
      <DestinationForm
        basePath={basePath}
        channels={CHANNELS.filter((channel) => channel.key === destination.channel)}
        destination={destination}
        makerspaceId={makerspaceId}
        onDone={() => setEditing(false)}
        options={options}
      />
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-bg p-3">
      <span className="font-medium text-ink">{destination.label}</span>
      <Badge tone="neutral">{destination.channel}</Badge>
      {destination.credential_set ? (
        <Badge tone="success">Configured</Badge>
      ) : (
        <Badge tone="danger">No credential</Badge>
      )}
      {destination.is_active ? null : <Badge tone="warn">Paused</Badge>}
      <span className="text-sm text-muted">
        {scopeCount === 0 ? "Everything" : `${scopeCount} scoped`}
      </span>
      <span className="ml-auto flex gap-2">
        <button className="desk-btn" onClick={() => setEditing(true)} type="button">
          Edit
        </button>
        <button className="desk-btn" onClick={onDelete} type="button">
          Remove
        </button>
      </span>
    </div>
  );
}

function DestinationForm({
  basePath,
  channels,
  destination,
  makerspaceId,
  onDone,
  options,
}: {
  basePath: string;
  channels: readonly { key: string; label: string }[];
  destination?: NotificationDestination;
  makerspaceId: number;
  onDone: () => void;
  options: ScopeOptions;
}) {
  const queryClient = useQueryClient();
  const [channel, setChannel] = useState(destination?.channel ?? channels[0]?.key ?? "slack");
  const [label, setLabel] = useState(destination?.label ?? "");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [chatId, setChatId] = useState(destination?.telegram_chat_id ?? "");
  const [isActive, setIsActive] = useState(destination?.is_active ?? true);
  const [scope, setScope] = useState<DestinationScope>(destination?.scope ?? EMPTY_SCOPE);
  const [error, setError] = useState("");

  const save = useMutation({
    mutationFn: () =>
      staffRequest<NotificationDestination>(
        destination ? `${basePath}/${destination.id}` : basePath,
        {
          method: destination ? "PUT" : "POST",
          body: JSON.stringify({
            channel,
            label,
            // Blank on edit means "keep the stored credential" — it cannot be read back,
            // so requiring it to rename a room would force a re-entry.
            ...(webhookUrl ? { webhook_url: webhookUrl } : {}),
            telegram_chat_id: channel === "telegram" ? chatId : "",
            is_active: isActive,
            scope,
          }),
        },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: DESTINATIONS_KEY(makerspaceId) });
      onDone();
    },
    onError: (err: unknown) =>
      setError(err instanceof Error ? err.message : "Could not save this room."),
  });

  return (
    <form
      className="grid gap-3 rounded-md border border-line bg-bg p-3"
      onSubmit={(event) => {
        event.preventDefault();
        setError("");
        save.mutate();
      }}
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="grid gap-1 text-sm">
          <span className="text-muted">Channel</span>
          <select
            className="desk-input"
            disabled={Boolean(destination)}
            onChange={(event) => setChannel(event.target.value as typeof channel)}
            value={channel}
          >
            {channels.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-sm">
          <span className="text-muted">Room name</span>
          <input
            className="desk-input"
            onChange={(event) => setLabel(event.target.value)}
            placeholder="Laser team"
            required
            value={label}
          />
        </label>
      </div>

      {channel === "telegram" ? (
        <label className="grid gap-1 text-sm">
          <span className="text-muted">Telegram chat ID</span>
          <input
            className="desk-input"
            onChange={(event) => setChatId(event.target.value)}
            placeholder="-1001234567890"
            required
            value={chatId}
          />
          <span className="text-xs text-muted">
            Rooms share this makerspace's bot — add the same bot to each group. Accept and
            reject buttons keep working because there is one bot and one webhook.
          </span>
        </label>
      ) : (
        <label className="grid gap-1 text-sm">
          <span className="text-muted">
            Incoming webhook URL{destination?.credential_set ? " (leave blank to keep)" : ""}
          </span>
          <input
            autoComplete="off"
            className="desk-input"
            onChange={(event) => setWebhookUrl(event.target.value)}
            placeholder="https://hooks.example.com/…"
            type="password"
            value={webhookUrl}
          />
        </label>
      )}

      <label className="flex items-center gap-2 text-sm">
        <input
          checked={isActive}
          onChange={(event) => setIsActive(event.target.checked)}
          type="checkbox"
        />
        <span>Deliver to this room</span>
      </label>

      <ScopePicker onChange={setScope} options={options} scope={scope} />

      {error ? <p className="text-sm text-danger">{error}</p> : null}
      <div className="flex gap-2">
        <button className="desk-btn" disabled={save.isPending} type="submit">
          {save.isPending ? "Saving…" : "Save room"}
        </button>
        <button className="desk-btn" onClick={onDone} type="button">
          Cancel
        </button>
      </div>
    </form>
  );
}

export function ScopePicker({
  onChange,
  options,
  scope,
}: {
  onChange: (scope: DestinationScope) => void;
  options: ScopeOptions;
  scope: DestinationScope;
}) {
  const groups = [
    { key: "machine_type_ids" as const, label: "Machine types", items: options.machineTypes },
    { key: "machine_ids" as const, label: "Machines", items: options.machines },
    { key: "category_ids" as const, label: "Categories", items: options.categories },
  ].filter((group) => group.items.length > 0);

  if (groups.length === 0) return null;

  return (
    <fieldset className="grid gap-2">
      <legend className="text-sm text-muted">
        Limit to (leave everything unticked to receive all alerts)
      </legend>
      <div className="grid gap-3 sm:grid-cols-3">
        {groups.map((group) => (
          <div key={group.key}>
            <p className="text-xs font-semibold uppercase text-muted">{group.label}</p>
            <div className="mt-1 grid max-h-40 gap-1 overflow-y-auto">
              {group.items.map((item) => (
                <label className="flex items-center gap-2 text-sm" key={item.id}>
                  <input
                    checked={scope[group.key].includes(item.id)}
                    onChange={(event) =>
                      onChange({
                        ...scope,
                        [group.key]: event.target.checked
                          ? [...scope[group.key], item.id]
                          : scope[group.key].filter((id) => id !== item.id),
                      })
                    }
                    type="checkbox"
                  />
                  <span>{item.name}</span>
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>
    </fieldset>
  );
}

/**
 * Scope targets a room or rule can name. Each list is optional — a makerspace with no
 * machines simply gets no machine column rather than an empty picker.
 */
export function useScopeOptions(makerspaceId: number): ScopeOptions {
  const machineTypes = useQuery({
    queryKey: ["machine-types", makerspaceId, "scope"],
    queryFn: () =>
      staffRequest<{ id: number; name: string }[]>(
        `/admin/makerspace/${makerspaceId}/machine-types`,
      ).catch(() => []),
  });
  const machines = useQuery({
    queryKey: ["machines", makerspaceId, "scope"],
    queryFn: () =>
      staffRequest<{ results?: { id: number; name: string }[] } | { id: number; name: string }[]>(
        `/admin/makerspace/${makerspaceId}/machines`,
      ).catch(() => []),
  });
  const categories = useQuery({
    queryKey: ["categories", makerspaceId, "scope"],
    queryFn: () =>
      staffRequest<{ results?: { id: number; name: string }[] } | { id: number; name: string }[]>(
        `/admin/makerspace/${makerspaceId}/categories`,
      ).catch(() => []),
  });

  return {
    machineTypes: unwrap(machineTypes.data),
    machines: unwrap(machines.data),
    categories: unwrap(categories.data),
  };
}

function unwrap(value: unknown): ScopeOption[] {
  if (Array.isArray(value)) return value as ScopeOption[];
  if (value && typeof value === "object" && Array.isArray((value as { results?: unknown }).results)) {
    return (value as { results: ScopeOption[] }).results;
  }
  return [];
}
