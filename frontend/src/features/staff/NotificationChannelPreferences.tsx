import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { DELIVERY_SETTINGS_KEY } from "./MakerspaceWebhookSettings";
import type {
  NotificationPreferenceCell,
  NotificationRulesResponse,
  PreferenceChange,
} from "./notificationRuleTypes";

type DeliverySettings = {
  slack_webhook_url_set: boolean;
  mattermost_webhook_url_set: boolean;
  discord_webhook_url_set: boolean;
  telegram_bot_token_set: boolean;
  telegram_group_chat_id: string;
};

type Props = {
  makerspaceId: number;
  rules: NotificationRulesResponse;
};

export function NotificationChannelPreferences({ makerspaceId, rules }: Props) {
  const queryClient = useQueryClient();
  const rulesPath = `/admin/makerspace/${makerspaceId}/notification-rules`;
  const queryKey = ["notification-rules", makerspaceId] as const;
  const settings = useQuery({
    queryKey: DELIVERY_SETTINGS_KEY(makerspaceId),
    queryFn: () =>
      staffRequest<DeliverySettings>(`/admin/makerspace/${makerspaceId}/api-settings`),
  });

  const updatePreference = useMutation({
    mutationFn: (change: PreferenceChange) =>
      staffRequest<NotificationRulesResponse>(rulesPath, {
        method: "PATCH",
        body: JSON.stringify({ preferences: [change] }),
      }),
    onMutate: async (change) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<NotificationRulesResponse>(queryKey);
      queryClient.setQueryData<NotificationRulesResponse>(queryKey, (current) =>
        current
          ? {
              ...current,
              preferences: applyPreferenceChange(current.preferences, change),
            }
          : current,
      );
      return { previous };
    },
    onError: (_error, _change, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData(queryKey, context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey });
    },
  });

  const warnings = deliveryWarnings(rules.preferences, settings.data);

  return (
    <section aria-labelledby="notification-channel-heading">
      <h4 id="notification-channel-heading" className="text-sm font-semibold text-ink">
        Notification channels
      </h4>
      <p className="mt-2 text-sm text-muted">
        Checked = enabled for that feature and channel. The Staff email notifications switch and
        per-member recipient toggles affect staff email only, not Telegram, Slack, or Mattermost.
      </p>
      <div className="mt-3 max-w-full overflow-x-auto rounded-md border border-line bg-bg">
        <table className="w-max min-w-full border-collapse text-sm">
          <caption className="sr-only">
            Checked boxes enable each notification channel for a feature.
          </caption>
          <thead className="bg-surface text-xs uppercase text-muted">
            <tr className="border-b border-line">
              <th className="px-3 py-2 text-left font-semibold" scope="col">
                Feature
              </th>
              {rules.channels.map((channel) => (
                <th
                  key={channel.key}
                  className="min-w-28 px-3 py-2 text-center font-semibold"
                  scope="col"
                >
                  {channel.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rules.features.map((feature) => (
              <tr key={feature.key} className="border-b border-line last:border-b-0">
                <th className="whitespace-nowrap px-3 py-2 text-left font-semibold text-ink" scope="row">
                  {feature.label}
                </th>
                {rules.channels.map((channel) => {
                  const cell = preferenceCell(rules.preferences, feature.key, channel.key);
                  const checked = cell?.enabled ?? false;
                  return (
                    <td key={channel.key} className="px-3 py-2 text-center">
                      <input
                        aria-label={`${checked ? "Disable" : "Enable"} ${channel.label} for ${feature.label}`}
                        className="h-4 w-4"
                        type="checkbox"
                        checked={checked}
                        disabled={updatePreference.isPending}
                        onChange={(event) =>
                          updatePreference.mutate({
                            feature: feature.key,
                            channel: channel.key,
                            enabled: event.target.checked,
                          })
                        }
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {warnings.length ? (
        <div
          className="mt-3 rounded-md border border-warn bg-warn/15 p-3 text-sm text-warn-ink"
          role="status"
          aria-live="polite"
        >
          <p className="font-semibold">Delivery setup needed</p>
          <ul className="mt-1 list-disc pl-5">
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {settings.error ? (
        <p className="mt-3 text-sm text-danger">Unable to check channel setup: {settings.error.message}</p>
      ) : null}
      {updatePreference.error ? (
        <p className="mt-3 text-sm text-danger" role="alert" aria-live="assertive">
          {updatePreference.error.message}
        </p>
      ) : null}
    </section>
  );
}

function preferenceCell(
  preferences: NotificationPreferenceCell[],
  feature: string,
  channel: string,
) {
  return preferences.find((cell) => cell.feature === feature && cell.channel === channel);
}

function applyPreferenceChange(
  preferences: NotificationPreferenceCell[],
  change: PreferenceChange,
) {
  const changed = preferences.some(
    (cell) => cell.feature === change.feature && cell.channel === change.channel,
  );
  if (!changed) return [...preferences, { ...change, source: "override" as const }];
  return preferences.map((cell) =>
    cell.feature === change.feature && cell.channel === change.channel
      ? { ...cell, enabled: change.enabled, source: "override" as const }
      : cell,
  );
}

function deliveryWarnings(
  preferences: NotificationPreferenceCell[],
  settings: DeliverySettings | undefined,
) {
  if (!settings) return [];
  const enabled = (channel: string) =>
    preferences.some((cell) => cell.channel === channel && cell.enabled);
  const warnings: string[] = [];
  if (enabled("slack") && !settings.slack_webhook_url_set) {
    warnings.push("Slack is enabled but its incoming webhook is not configured.");
  }
  if (enabled("mattermost") && !settings.mattermost_webhook_url_set) {
    warnings.push("Mattermost is enabled but its incoming webhook is not configured.");
  }
  if (enabled("discord") && !settings.discord_webhook_url_set) {
    warnings.push("Discord is enabled but its incoming webhook is not configured.");
  }
  if (
    enabled("telegram") &&
    (!settings.telegram_bot_token_set || !settings.telegram_group_chat_id?.trim())
  ) {
    warnings.push("Telegram is enabled but its bot token or group chat ID is not configured.");
  }
  return warnings;
}
