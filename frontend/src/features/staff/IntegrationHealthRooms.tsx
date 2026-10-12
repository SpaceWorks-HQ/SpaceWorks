import { Badge } from "../../components/ui";

// The backend has reported per-room delivery health since the destinations work
// (`integrations/health.py` -> `chat_destinations`); the console never rendered it, so the
// one surface where an operator could learn a room's webhook was revoked was invisible.

type LastFailure = { error: string; at: string } | null;

export type ChatRoomHealth = {
  id: number;
  channel: string;
  label: string;
  is_active: boolean;
  configured: boolean;
  last_sent_at: string | null;
  failed: number;
  last_failure: LastFailure;
};

export type LegacyChannelHealth = {
  configured: boolean;
  last_sent_at: string | null;
  failed: number;
  last_failure: LastFailure;
};

export type ChatDestinationsHealth = {
  status?: "ok" | "warn" | "error" | "unknown";
  detail?: string;
  destinations?: ChatRoomHealth[];
  legacy_deliveries?: Record<string, LegacyChannelHealth>;
};

const CHANNEL_LABELS: Record<string, string> = {
  telegram: "Telegram",
  slack: "Slack",
  mattermost: "Mattermost",
  discord: "Discord",
  webhook: "Signed webhook",
};

export function IntegrationHealthRooms({
  section,
  formatTime,
}: {
  section?: ChatDestinationsHealth;
  formatTime: (value: string) => string;
}) {
  const rooms = section?.destinations ?? [];
  const legacy = Object.entries(section?.legacy_deliveries ?? {});
  if (!rooms.length && !legacy.length) {
    return <p className="text-sm text-muted">No chat or webhook rooms are configured.</p>;
  }
  return (
    <ul className="grid gap-2 sm:grid-cols-2">
      {rooms.map((room) => (
        <RoomRow
          key={`room-${room.id}`}
          title={`${CHANNEL_LABELS[room.channel] ?? room.channel} - ${room.label}`}
          configured={room.configured}
          inactive={!room.is_active}
          health={room}
          formatTime={formatTime}
        />
      ))}
      {legacy.map(([channel, health]) => (
        <RoomRow
          key={`legacy-${channel}`}
          title={`${CHANNEL_LABELS[channel] ?? channel} (space-wide)`}
          configured={health.configured}
          inactive={false}
          health={health}
          formatTime={formatTime}
        />
      ))}
    </ul>
  );
}

function RoomRow({
  title,
  configured,
  inactive,
  health,
  formatTime,
}: {
  title: string;
  configured: boolean;
  inactive: boolean;
  health: LegacyChannelHealth;
  formatTime: (value: string) => string;
}) {
  return (
    <li className="min-w-0 rounded-md border border-line bg-surface p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="min-w-0 break-words font-semibold text-ink">{title}</p>
        {!configured ? (
          <Badge tone="neutral">Not configured</Badge>
        ) : inactive ? (
          <Badge tone="neutral">Inactive</Badge>
        ) : health.failed > 0 ? (
          <Badge tone="danger">{`${health.failed} failed`}</Badge>
        ) : (
          <Badge tone="success">Healthy</Badge>
        )}
      </div>
      <p className="mt-1 text-xs text-muted">
        {health.last_sent_at ? `Last sent ${formatTime(health.last_sent_at)}` : "Never sent"}
      </p>
      {health.last_failure ? (
        <p className="mt-2 break-words text-danger">
          {`Last delivery failed ${formatTime(health.last_failure.at)}: ${health.last_failure.error || "no detail"}`}
        </p>
      ) : null}
    </li>
  );
}
