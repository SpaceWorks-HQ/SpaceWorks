/** Chat channels a room may post into. Ordered as the picker shows them. */
export const CHANNELS = [
  { key: "slack", label: "Slack" },
  { key: "mattermost", label: "Mattermost" },
  { key: "discord", label: "Discord" },
  { key: "telegram", label: "Telegram" },
  { key: "webhook", label: "Signed webhook" },
] as const;

export const DESTINATIONS_KEY = (makerspaceId: number) =>
  ["notification-destinations", makerspaceId] as const;
