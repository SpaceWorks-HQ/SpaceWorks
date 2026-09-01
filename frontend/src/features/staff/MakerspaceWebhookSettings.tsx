import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { type Makerspace, useStaffGet } from "./StaffPanels";

type ApiSettings = {
  slack_webhook_url_set: boolean;
  mattermost_webhook_url_set: boolean;
  discord_webhook_url_set: boolean;
};

type ProviderCardProps = {
  configured: boolean;
  label: string;
  makerspaceId: number;
  provider: "slack" | "mattermost" | "discord";
};

// Read webhook state under a dedicated cache key (same endpoint) so saving/clearing a
// webhook never invalidates the shared ["api-settings", id] query that the SMTP form and
// its unsaved edits depend on. The notification channel matrix reads the same key, so its
// configuration warnings still refresh immediately after a webhook is saved.
export const DELIVERY_SETTINGS_KEY = (makerspaceId: number) => [
  "api-settings",
  makerspaceId,
  "delivery",
];

export function MakerspaceWebhookSettings({ makerspace }: { makerspace: Makerspace }) {
  const settings = useStaffGet<ApiSettings>(
    DELIVERY_SETTINGS_KEY(makerspace.id),
    `/admin/makerspace/${makerspace.id}/api-settings`,
  );

  return (
    <div className="rounded-md border border-line bg-bg p-4">
      <div className="grid max-w-2xl gap-2">
        <h3 className="text-base font-semibold text-ink">Chat webhooks</h3>
        <p className="text-sm text-muted">
          Add incoming webhook URLs for Slack, Mattermost or Discord. Saving a webhook
          configures the destination; enable delivery separately in the notification channel
          matrix below. Each channel is also its own module, so a space ships only the ones
          it uses.
        </p>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <ProviderCard
          configured={settings.data?.slack_webhook_url_set ?? false}
          label="Slack"
          makerspaceId={makerspace.id}
          provider="slack"
        />
        <ProviderCard
          configured={settings.data?.mattermost_webhook_url_set ?? false}
          label="Mattermost"
          makerspaceId={makerspace.id}
          provider="mattermost"
        />
        <ProviderCard
          configured={settings.data?.discord_webhook_url_set ?? false}
          label="Discord"
          makerspaceId={makerspace.id}
          provider="discord"
        />
      </div>
      {settings.isLoading ? (
        <p className="mt-3 text-sm text-muted">Loading webhook settings...</p>
      ) : null}
      {settings.error ? (
        <p className="mt-3 text-sm text-danger">{settings.error.message}</p>
      ) : null}
    </div>
  );
}

function ProviderCard({ configured, label, makerspaceId, provider }: ProviderCardProps) {
  const queryClient = useQueryClient();
  const [webhookUrl, setWebhookUrl] = useState("");
  const field = `${provider}_webhook_url`;
  const path = `/admin/makerspace/${makerspaceId}/api-settings`;

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: DELIVERY_SETTINGS_KEY(makerspaceId) });

  const saveWebhook = useMutation({
    mutationFn: (value: string) =>
      staffRequest<ApiSettings>(path, {
        method: "PATCH",
        body: JSON.stringify({ [field]: value }),
      }),
    onSuccess: () => {
      setWebhookUrl("");
      invalidate();
    },
  });

  const clearWebhook = useMutation({
    mutationFn: () =>
      staffRequest<ApiSettings>(path, {
        method: "PATCH",
        body: JSON.stringify({ [field]: "" }),
      }),
    onSuccess: () => {
      setWebhookUrl("");
      invalidate();
    },
  });

  const pending = saveWebhook.isPending || clearWebhook.isPending;

  return (
    <section className="rounded-md border border-line bg-surface p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-ink">{label}</h4>
        <Badge tone={configured ? "success" : "neutral"}>
          {configured ? "Configured" : "Not configured"}
        </Badge>
      </div>
      <p className="mt-2 text-sm text-muted">
        Paste an incoming webhook URL. The saved URL is never displayed again.
      </p>
      <label className="mt-3 block text-sm font-semibold text-ink">
        {label} incoming webhook URL
        <input
          autoComplete="new-password"
          className="desk-input mt-1 w-full"
          type="password"
          value={webhookUrl}
          onChange={(event) => setWebhookUrl(event.target.value)}
        />
      </label>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <button
          className="desk-button-primary w-full"
          type="button"
          disabled={!webhookUrl.trim() || pending}
          onClick={() => saveWebhook.mutate(webhookUrl.trim())}
        >
          {saveWebhook.isPending ? "Saving..." : `Save ${label} webhook`}
        </button>
        <button
          className="desk-button w-full"
          type="button"
          disabled={!configured || pending}
          onClick={() => clearWebhook.mutate()}
        >
          {clearWebhook.isPending ? "Clearing..." : `Clear ${label} webhook`}
        </button>
      </div>
      {saveWebhook.error ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {saveWebhook.error.message}
        </p>
      ) : null}
      {clearWebhook.error ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {clearWebhook.error.message}
        </p>
      ) : null}
    </section>
  );
}
