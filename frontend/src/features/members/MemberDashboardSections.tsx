import type { MemberActivity } from "./MemberActivity";

/** The member dashboard's history, money and notices (D8).
 *
 * Rendered only when the `membership` module is on, because the endpoint that feeds it
 * is module-gated. Notices are DERIVED server-side from the member's own rows rather
 * than read from the staff notification table, which has no recipient column.
 */
export function MemberNotices({ notices }: { notices: MemberActivity["notices"] }) {
  if (!notices?.length) return null;
  return (
    <section className="desk-panel p-5">
      <h2 className="title-panel">Needs your attention</h2>
      <ul className="mt-3 space-y-2">
        {notices.map((notice) => (
          <li
            className={`rounded-md border px-3 py-2 text-sm ${borderFor(notice.level)}`}
            key={notice.event + notice.title}
          >
            <span className="font-medium text-ink">{notice.title}</span>
            {notice.body ? <p className="mt-1 text-muted">{notice.body}</p> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function MemberDues({ dues }: { dues: MemberActivity["membership_dues"] }) {
  if (!dues) return null;
  // `null` is "we could not read the ledger", not "nothing is owed". Kept apart all the
  // way to the screen: collapsing them here would quietly tell a member they are clear.
  const unavailable = dues.outstanding_by_currency === null;
  const outstanding = Object.entries(dues.outstanding_by_currency ?? {});
  return (
    <section className="desk-panel p-5">
      <h2 className="title-panel">Membership fee</h2>
      <p className="mt-2 text-sm text-muted">
        Dues <span className="font-mono text-ink">{dues.dues_amount}</span>
      </p>
      {unavailable ? (
        <p className="mt-1 text-sm text-muted">
          Outstanding balance is unavailable right now.
        </p>
      ) : outstanding.length ? (
        <p className="mt-1 text-sm text-muted">
          Outstanding{" "}
          {outstanding.map(([currency, amount]) => (
            <span className="font-mono text-ink" key={currency}>
              {amount} {currency.toUpperCase()}{" "}
            </span>
          ))}
        </p>
      ) : (
        <p className="mt-1 text-sm text-muted">Nothing outstanding.</p>
      )}
    </section>
  );
}

export function MemberHistory({
  loans,
  requests,
}: {
  loans: MemberActivity["loan_history"];
  requests: MemberActivity["request_history"];
}) {
  if (!loans?.length && !requests?.length) return null;
  return (
    <section className="desk-panel p-5">
      <h2 className="title-panel">Your history</h2>
      {requests?.length ? (
        <>
          <h3 className="eyebrow mt-3">Requests</h3>
          <ul className="mt-2 space-y-1 text-sm text-muted">
            {requests.map((row, index) => (
              <li key={`${row.created_at}-${index}`}>
                <span className="text-ink">{row.status.replace(/_/g, " ")}</span>
                {" · "}
                {new Date(row.created_at).toLocaleDateString()}
                {" · "}
                {row.item_count} item(s), {row.returned_quantity} returned
                {row.damaged_quantity || row.missing_quantity ? (
                  <span className="text-danger">
                    {" · "}
                    {row.damaged_quantity} damaged, {row.missing_quantity} missing
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {loans?.length ? (
        <>
          <h3 className="eyebrow mt-4">Returned items</h3>
          <ul className="mt-2 space-y-1 text-sm text-muted">
            {loans.map((row, index) => (
              <li key={`${row.label}-${index}`}>
                <span className="text-ink">{row.label}</span>
                {row.returned_at ? (
                  <> · returned {new Date(row.returned_at).toLocaleDateString()}</>
                ) : null}
                {row.returned_late ? <span className="text-warn"> · late</span> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}

function borderFor(level: string) {
  if (level === "critical") return "border-danger/40 bg-danger/10";
  if (level === "warning") return "border-warn/40 bg-warn/10";
  return "border-line";
}
