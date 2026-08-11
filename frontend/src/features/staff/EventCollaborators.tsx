import { useState } from "react";

import {
  useEventCollaborators,
  useRemoveEventCollaborator,
  useReplaceEventCollaborators,
} from "./eventsApi";

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

const STATUS_LABEL: Record<string, string> = {
  invited: "Invited — waiting for them to accept",
  accepted: "Accepted — their members can register",
  declined: "Declined",
};

/** Host-side collaborator management for one event.
 *
 * Invitation is by SLUG, not a picker, and that is deliberate rather than lazy: a host has
 * no authority to enumerate other makerspaces, so offering a browsable list would leak the
 * existence and names of spaces it does not administer. The partner then has to accept
 * before any of its members become eligible, so one space cannot attach itself — or be
 * attached — to another's event unilaterally.
 */
export function EventCollaborators({
  makerspaceId,
  eventId,
}: {
  makerspaceId: number;
  eventId: number;
}) {
  const [slug, setSlug] = useState("");
  const collaborators = useEventCollaborators(eventId);
  const replace = useReplaceEventCollaborators(makerspaceId, eventId);
  const remove = useRemoveEventCollaborator(makerspaceId, eventId);
  const rows = collaborators.data ?? [];
  const error = replace.error || remove.error || collaborators.error;

  const invite = () => {
    const wanted = slug.trim().toLowerCase();
    if (!wanted) return;
    // The endpoint REPLACES the set, so send every slug that should remain plus the new
    // one; sending only the addition would silently remove every existing partner. Declined
    // rows are included so they are NOT deleted -- the service preserves their answer, so
    // adding one partner cannot reopen somebody else's refusal.
    const slugs = Array.from(
      new Set([...rows.map((row) => row.makerspace_slug), wanted]),
    );
    replace.mutate(slugs, { onSuccess: () => setSlug("") });
  };

  return (
    <section aria-labelledby="collaborators-title" className="mt-5">
      <h3 id="collaborators-title" className="mb-1 font-semibold text-ink">
        Partner makerspaces
      </h3>
      <p className="mb-3 text-sm text-muted">
        Invite another makerspace by its slug and its members can register for this event,
        even when the event is not public. They must accept the invitation first. You invite
        by slug because makerspaces are not browsable from here.
      </p>

      {rows.length ? (
        <ul className="mb-3 space-y-2 text-sm">
          {rows.map((row) => (
            <li key={row.id} className="flex flex-wrap items-center justify-between gap-2">
              <span>
                <span className="font-medium text-ink">{row.makerspace_name}</span>{" "}
                <span className="text-muted">({row.makerspace_slug})</span>
                <span className="block text-muted">
                  {STATUS_LABEL[row.status] ?? row.status}
                </span>
              </span>
              <button
                type="button"
                className={`desk-button text-danger ${FOCUS}`}
                disabled={remove.isPending}
                onClick={() => remove.mutate(row.id)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-3 text-sm text-muted">No partner makerspaces yet.</p>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-sm font-semibold text-ink">
          Makerspace slug
          <input
            className={`desk-input ${FOCUS}`}
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
            placeholder="partner-space"
          />
        </label>
        <button
          type="button"
          className={`desk-button ${FOCUS}`}
          disabled={!slug.trim() || replace.isPending}
          onClick={invite}
        >
          {replace.isPending ? "Inviting…" : "Invite"}
        </button>
      </div>

      {error ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {error instanceof Error ? error.message : "Could not update partners."}
        </p>
      ) : null}
    </section>
  );
}
