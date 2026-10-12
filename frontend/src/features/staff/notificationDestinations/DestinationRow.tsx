import { useState } from "react";

import { Badge } from "../../../components/ui";
import { type NotificationDestination } from "../notificationDestinationTypes";
import { CHANNELS } from "./channels";
import { DestinationForm } from "./DestinationForm";
import { type ScopeOptions } from "./scopeOptions";

export function DestinationRow({
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
        <button className="desk-button" onClick={() => setEditing(true)} type="button">
          Edit
        </button>
        <button className="desk-button-danger" onClick={onDelete} type="button">
          Remove
        </button>
      </span>
    </div>
  );
}
