import { Link } from "react-router-dom";

import { EmptyState } from "../../../../components/ui";
import type { Machine, MachineType, MachineStatus } from "../../machinesApi";

type Props = {
  machineTypes: MachineType[];
  machines: Machine[];
  machinesLoading: boolean;
  machinesFailed: boolean;
  typesLoading: boolean;
  typesFailed: boolean;
  hrefFor: (machineType: MachineType) => string;
};

const focusRing = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

// Only the states worth surfacing on a card. `idle` is the resting state and says nothing;
// `reserved` is normal scheduling. What an operator scans this grid for is "what is busy"
// and "what is not usable".
const HIGHLIGHT: { status: MachineStatus; label: string; tone: string }[] = [
  { status: "running", label: "running", tone: "bg-success text-on-success" },
  { status: "maintenance", label: "in maintenance", tone: "bg-warn text-on-warn" },
  { status: "offline", label: "offline", tone: "bg-danger text-bg" },
];

/** The machines index: one card per reachable machine type.
 *
 * The card grid is built from the SERVER-SCOPED type list merged with the types nested in
 * the machines response -- never from effective action strings. A `MANAGE_MACHINES` grant
 * is scoped per ROLE through link tables, no links means no machines, and a membership with
 * a null `assigned_role` is EXEMPT: none of that is expressible client-side, and four
 * previous phases have shipped a bug by trying.
 */
export function MachineTypeCards({
  machineTypes,
  machines,
  machinesLoading,
  machinesFailed,
  typesLoading,
  typesFailed,
  hrefFor,
}: Props) {
  if (typesLoading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label="Loading machine types">
        {[0, 1, 2].map((slot) => (
          <div key={slot} className="h-28 animate-pulse rounded-xl border border-line bg-surface" />
        ))}
      </div>
    );
  }

  // An empty grid is only honest after a SUCCESSFUL load -- the same rule the per-type
  // machine list follows. A failed request that renders "no machine types" tells an
  // operator their console is empty when it is merely broken.
  if (!typesFailed && !machineTypes.length) {
    return (
      <EmptyState
        title="No machine types available"
        description="No reachable machine types are configured for you in this makerspace."
      />
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {machineTypes.map((machineType) => {
        const owned = machines.filter((machine) => machine.machine_type.id === machineType.id);
        const highlights = HIGHLIGHT.map(({ status, label, tone }) => ({
          label,
          tone,
          count: owned.filter((machine) => machine.status === status).length,
        })).filter((entry) => entry.count > 0);

        return (
          <Link
            key={machineType.id}
            to={hrefFor(machineType)}
            className={`group grid gap-3 rounded-xl border border-line bg-panel p-4 shadow-soft transition-all hover:-translate-y-0.5 hover:border-accent hover:shadow-soft-lg ${focusRing}`}
          >
            <span className="flex min-w-0 items-center gap-2">
              {machineType.icon ? <span aria-hidden="true" className="text-lg">{machineType.icon}</span> : null}
              <span className="truncate font-display text-lg font-semibold text-ink">{machineType.name}</span>
            </span>
            <span className="flex flex-wrap items-center gap-2">
              {/* A count is stated as fact, so it must not be stated while the fleet is
                  still loading or after the request failed. */}
              {machinesLoading ? (
                <span className="font-mono text-xs text-muted">counting…</span>
              ) : machinesFailed ? (
                <span className="font-mono text-xs text-muted">count unavailable</span>
              ) : (
                <span className="chip">{owned.length} {owned.length === 1 ? "machine" : "machines"}</span>
              )}
              {!machinesLoading && !machinesFailed
                ? highlights.map((entry) => (
                    <span key={entry.label} className={`status-box ${entry.tone}`}>
                      {entry.count} {entry.label}
                    </span>
                  ))
                : null}
            </span>
          </Link>
        );
      })}
    </div>
  );
}
