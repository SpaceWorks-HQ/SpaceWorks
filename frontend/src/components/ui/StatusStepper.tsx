const STAGES = ["Requested", "Approved", "Collected", "Returned"] as const;

const STEP_TONE_CLASSES = [
  "border-accent bg-accent text-on-accent",
  "border-warn bg-warn text-on-warn",
  "border-secondary bg-secondary text-on-secondary",
  "border-success bg-success text-on-success",
] as const;

function statusStageIndex(status: string): number {
  switch (status) {
    case "accepted":
      return 1;
    case "issued":
    case "partially_returned":
      return 2;
    case "returned":
    case "closed_with_issue":
      return 3;
    case "draft":
    case "pending_approval":
    case "rejected":
    default:
      return 0;
  }
}

export function statusStageLabel(status: string): string {
  if (status === "rejected") return "Rejected";
  return STAGES[statusStageIndex(status)] ?? STAGES[0];
}

function StepBox({
  step,
  label,
  state,
  rejected,
}: {
  step: number;
  label: string;
  state: "completed" | "current" | "upcoming" | "issue";
  rejected: boolean;
}) {
  const className = (rejected && step === 0) || state === "issue"
    ? "status-box status-box-danger"
    : state === "completed" || state === "current"
      ? `status-box ${STEP_TONE_CLASSES[step] ?? STEP_TONE_CLASSES[0]} shadow-soft`
      : "status-box";

  return (
    <span
      className={`${className} w-full flex-col leading-tight`}
      aria-current={state === "current" ? "step" : undefined}
    >
      <span className="font-bold opacity-70">{step + 1}</span>
      <span className="min-w-0 break-words">{label}</span>
    </span>
  );
}

function RejectedBadge() {
  return <span className="status-box status-box-danger">Rejected</span>;
}

export function StatusStepper({ status }: { status: string }) {
  const rejected = status === "rejected";
  const activeIndex = rejected ? 0 : statusStageIndex(status);
  // A clean fully-returned request shows the final step as DONE (green) — the
  // flow is finished. A closure WITH an issue (lost/damaged) must NOT read as a
  // clean success: its final step renders as danger (red) instead.
  const complete = status === "returned";
  const closedWithIssue = status === "closed_with_issue";

  return (
    <nav
      aria-label={`Request status: ${statusStageLabel(status)}`}
      className="w-full"
    >
      <ol className="grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] items-start gap-2">
        {STAGES.map((stage, index) => {
          const state =
            index < activeIndex
              ? "completed"
              : index === activeIndex
                ? closedWithIssue
                  ? "issue"
                  : complete
                    ? "completed"
                    : "current"
                : "upcoming";

          return (
            <li
              className="flex min-w-0 flex-col items-center text-center"
              key={stage}
            >
              <span className="flex w-full min-w-0 flex-col items-center gap-1">
                <StepBox
                  step={index}
                  label={stage}
                  state={state}
                  rejected={rejected}
                />
                {rejected && index === 0 ? <RejectedBadge /> : null}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
