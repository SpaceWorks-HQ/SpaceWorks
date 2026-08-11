import { useCollaborationInbox, useRespondToCollaboration } from "./eventsApi";

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

/** Invitations this makerspace has received to co-host another space's event.
 *
 * The collaborator side of invite → accept, and the reason it exists as its own surface: a
 * host cannot accept on a partner's behalf, so without this the partner's members could
 * never become eligible. Renders nothing at all when the inbox is empty, so a space that
 * never collaborates sees no new UI.
 */
export function CollaborationInbox({ makerspaceId }: { makerspaceId: number }) {
  const inbox = useCollaborationInbox(makerspaceId);
  const respond = useRespondToCollaboration(makerspaceId);
  const rows = inbox.data ?? [];

  if (!rows.length) return null;

  return (
    <section
      aria-labelledby="collaboration-inbox-title"
      className="mb-5 rounded-xl border border-line bg-bg p-4"
    >
      <h3 id="collaboration-inbox-title" className="mb-1 font-semibold text-ink">
        Invitations from other makerspaces
      </h3>
      <p className="mb-3 text-sm text-muted">
        Accepting lets your members register for that makerspace&apos;s event. The host still
        owns and runs the event.
      </p>
      <ul className="space-y-3 text-sm">
        {rows.map((row) => (
          <li key={row.id} className="flex flex-wrap items-center justify-between gap-2">
            <span>
              <span className="font-medium text-ink">{row.event_title}</span>
              <span className="block text-muted">
                Hosted by {row.host_name} · {new Date(row.starts_at).toLocaleString()}
              </span>
            </span>
            {row.status === "invited" ? (
              <span className="flex gap-2">
                <button
                  type="button"
                  className={`desk-button-primary ${FOCUS}`}
                  disabled={respond.isPending}
                  onClick={() => respond.mutate({ id: row.id, accept: true })}
                >
                  Accept
                </button>
                <button
                  type="button"
                  className={`desk-button ${FOCUS}`}
                  disabled={respond.isPending}
                  onClick={() => respond.mutate({ id: row.id, accept: false })}
                >
                  Decline
                </button>
              </span>
            ) : (
              <span className="text-muted">{row.status}</span>
            )}
          </li>
        ))}
      </ul>
      {respond.error ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {respond.error instanceof Error ? respond.error.message : "Could not respond."}
        </p>
      ) : null}
    </section>
  );
}
