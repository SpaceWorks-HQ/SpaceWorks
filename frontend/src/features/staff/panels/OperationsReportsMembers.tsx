import { BarChart, DataState, ReportTable, StatCards } from "./OperationsReportsParts";
import { Panel } from "./shared";
import { useMemberActivityReport, type MemberActivityReportProps, type MemberActivityRow } from "./operationsReportsMembersApi";

type Props = MemberActivityReportProps;

export function OperationsReportsMembers(props: Props) {
  const report = useMemberActivityReport(props);
  const rows = report.data?.typed_rows ?? [];
  if (!props.enabled) return null;

  return (
    <Panel title="Member activity">
      <p className="text-sm text-muted">
        Aggregate membership health for the selected scope.
      </p>
      <p className="mt-1 text-sm text-muted">This report contains aggregate makerspace counts only; it does not include member identities or contact details.</p>
      <p className="mt-2 text-xs text-muted">
        Current-state counts describe today&apos;s membership snapshot. Activations and revocations use current lifecycle timestamps in the selected date range.
      </p>
      <p className="mt-1 text-xs text-muted">These are current lifecycle timestamps, not immutable event-history counts.</p>
      <DataState loading={report.isLoading} error={report.error} empty={!rows.length}>
        {props.aggregate ? (
          <div className="mt-4 space-y-4">
            {rows.map((row) => (
              <section key={row.makerspace_id ?? row.makerspace_name} className="rounded-md border border-line p-4">
                <h3 className="title-section">{row.makerspace_name}</h3>
                <MemberActivityMetrics row={row} />
              </section>
            ))}
          </div>
        ) : <MemberActivityMetrics row={rows[0]} />}
      </DataState>
    </Panel>
  );
}

function MemberActivityMetrics({ row }: { row: MemberActivityRow }) {
  return (
    <>
      <StatCards stats={[
        ["Active members (current)", row.active_members],
        ["Pending requests (current)", row.pending_requests],
        ["Open invitations (current)", row.open_invites],
        ["Verified members (current)", row.verified_members],
        ["Activations (current timestamp in range)", row.new_members],
        ["Revocations (current timestamp in range)", row.revoked_members],
        ["Active referral joins decided in range", row.referred_joins],
      ]} />
      <div className="mt-4">
        <BarChart rows={[
          { label: "Active", value: row.active_members },
          { label: "Pending", value: row.pending_requests },
          { label: "Invited", value: row.open_invites },
          { label: "Verified", value: row.verified_members },
        ]} valueLabel="members" />
      </div>
      <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
        <MetricDetail label="Membership policy" value={humanizePolicy(row.membership_policy)} />
        <MetricDetail label="Referrals" value={row.referrals_enabled ? "Enabled" : "Disabled"} />
      </dl>
      <ReportTable data={{ rows: [Object.keys(row), Object.values(row).map((value) => value ?? null)] }} />
    </>
  );
}

function MetricDetail({ label, value }: { label: string; value: string }) {
  return <div className="rounded-md border border-line bg-bg px-3 py-2"><dt className="text-xs text-muted">{label}</dt><dd className="font-medium text-ink">{value}</dd></div>;
}

function humanizePolicy(policy: string) {
  if (policy === "invite_only") return "Invite only";
  if (policy === "request") return "Request approval";
  if (policy === "open") return "Open signup";
  return policy.replace(/_/g, " ");
}
