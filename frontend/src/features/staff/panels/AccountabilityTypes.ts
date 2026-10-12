export type Offender = {
  requester_id: number;
  username: string;
  access_status: string;
  restriction_reason: string;
  damaged: number;
  missing: number;
  total_issues: number;
  total_quantity: number;
};
export type Overdue = {
  type: "request" | "direct";
  reference_id: number;
  requester_username: string;
  label: string;
  due_at: string;
  days_overdue: number;
};
export type Restriction = { requester_id: number; username: string; access_status: string; restriction_reason: string };
export type ProblemReportItem = { id: number; product_name: string; issued_quantity: number; tracking_mode: string };
export type ProblemReport = { id: number; requester_username: string; label: string; note: string; created_at: string; items: ProblemReportItem[] };
export type AnonymousAccountability = { damaged: number; missing: number; total_issues: number; total_quantity: number };
export type AccountabilityResponse = {
  repeat_offenders: Offender[];
  // Account-less loans all share one requester principal, so they are excluded from the
  // per-person ranking above and reported as a total instead. Rendering it is not
  // optional: without it the panel reads "No damage or loss on record" while account-less
  // incidents exist.
  anonymous_accountability?: AnonymousAccountability;
  overdue: Overdue[];
  restrictions: Restriction[];
  problem_reports: ProblemReport[];
  truncated: { repeat_offenders: boolean; overdue: boolean; problem_reports: boolean };
};
export type TriageOutcome = "no_issue" | "damaged" | "missing" | "needs_fix";

export const OUTCOME_OPTIONS: Array<{ value: TriageOutcome; label: string }> = [
  { value: "no_issue", label: "No issue" },
  { value: "damaged", label: "Damaged" },
  { value: "missing", label: "Missing" },
  { value: "needs_fix", label: "Needs fix" },
];
