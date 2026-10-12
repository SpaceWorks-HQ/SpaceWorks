import { useMemo, useState } from "react";

import { Badge } from "../../../../components/ui";
import { useCardMemberships, useIssueCard } from "./api";
import type { CardMembershipRow } from "./types";

const memberLabel = (row: CardMembershipRow) => row.user.display_name || row.user.username;

/** The issue queue: memberships that hold no active card.
 *
 *  A member already carrying a card is absent rather than disabled — issuing a second one
 *  is the `reissue` action on the card, which is where the lost/stolen reason is recorded.
 */
export function IssueRoster({
  makerspaceId,
  cardedMembershipIds,
}: {
  makerspaceId: number;
  cardedMembershipIds: number[];
}) {
  const memberships = useCardMemberships(makerspaceId);
  const issue = useIssueCard(makerspaceId);
  const [names, setNames] = useState<Record<number, string>>({});
  const carded = useMemo(() => new Set(cardedMembershipIds), [cardedMembershipIds]);
  const rows = (memberships.data ?? []).filter((row) => !carded.has(row.id));

  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <h3 className="title-section">Members without a card</h3>
      {memberships.isLoading ? <p className="mt-2 text-sm text-muted">Loading the roster…</p> : null}
      {memberships.error ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {memberships.error instanceof Error ? memberships.error.message : "Could not load members."}
        </p>
      ) : null}
      {!memberships.isLoading && !rows.length ? (
        <p className="mt-2 text-sm text-muted">Every member on the roster holds an active card.</p>
      ) : null}
      <ul className="mt-3 grid gap-2">
        {rows.map((row) => (
          <li
            key={row.id}
            className="flex flex-col gap-2 rounded-lg border border-line bg-panel p-3 sm:flex-row sm:items-center"
          >
            <span className="min-w-0 flex-1 truncate text-sm text-ink">{memberLabel(row)}</span>
            {row.status ? <Badge tone={row.status === "active" ? "success" : "warn"}>{row.status}</Badge> : null}
            <label className="sr-only" htmlFor={`printed-name-${row.id}`}>
              Printed name for {memberLabel(row)}
            </label>
            <input
              id={`printed-name-${row.id}`}
              className="desk-input sm:w-56"
              placeholder="Printed name (optional)"
              value={names[row.id] ?? ""}
              onChange={(event) => setNames({ ...names, [row.id]: event.target.value })}
            />
            <button
              className="desk-button-primary"
              type="button"
              disabled={issue.isPending}
              onClick={() =>
                issue.mutate({ membershipId: row.id, printedName: names[row.id]?.trim() || undefined })
              }
            >
              Issue card
            </button>
          </li>
        ))}
      </ul>
      {issue.error ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {issue.error instanceof Error ? issue.error.message : "Could not issue that card."}
        </p>
      ) : null}
    </div>
  );
}
