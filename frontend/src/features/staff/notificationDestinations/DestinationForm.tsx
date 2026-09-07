import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../../lib/api";
import {
  type NotificationDestination,
  type DestinationScope,
  EMPTY_SCOPE,
} from "../notificationDestinationTypes";
import { DESTINATIONS_KEY } from "./channels";
import { ScopePicker } from "./ScopePicker";
import { type ScopeOptions } from "./scopeOptions";

export function DestinationForm({
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
  const [signingSecret, setSigningSecret] = useState("");
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
            ...(channel === "webhook" && signingSecret ? { signing_secret: signingSecret } : {}),
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

      {channel === "webhook" ? (
        <label className="grid gap-1 text-sm">
          <span className="text-muted">
            Signing secret{destination?.signing_secret_set ? " (leave blank to keep)" : ""}
          </span>
          <input
            autoComplete="off"
            className="desk-input"
            minLength={16}
            onChange={(event) => setSigningSecret(event.target.value)}
            placeholder="At least 16 characters; your endpoint verifies X-SpaceWorks-Signature with it"
            required={!destination?.signing_secret_set}
            type="password"
            value={signingSecret}
          />
          <span className="text-xs text-muted">
            Every notification routed to this endpoint arrives as JSON with an HMAC-SHA256
            signature over the exact body. It is the same message a chat room would receive.
          </span>
        </label>
      ) : null}

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
        <button className="desk-button-primary" disabled={save.isPending} type="submit">
          {save.isPending ? "Saving…" : "Save room"}
        </button>
        <button className="desk-button-ghost" onClick={onDone} type="button">
          Cancel
        </button>
      </div>
    </form>
  );
}
