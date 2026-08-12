import { Panel, useStaffGet, type Makerspace } from "./shared";

type DashboardCounts = {
  scope_mode: "machine" | "full";
  overdue_loans?: number;
  pending_requests?: number;
  awaiting_issue?: number;
  open_problem_reports?: number;
  low_stock?: number;
  pending_prints?: number;
  active_prints?: number;
  prints_awaiting_collection?: number;
  failed_emails?: number;
  stocktakes_awaiting_approval?: number;
  warranty_expiring?: number;
  maintenance_overdue?: number;
  pending_payments?: number;
};

type Tile = {
  key: Exclude<keyof DashboardCounts, "scope_mode">;
  label: string;
  actionNeeded: boolean;
};

const TILES: Tile[] = [
  { key: "overdue_loans", label: "Overdue loans", actionNeeded: true },
  { key: "pending_requests", label: "Pending requests", actionNeeded: true },
  { key: "awaiting_issue", label: "Awaiting issue", actionNeeded: true },
  { key: "open_problem_reports", label: "Problem reports", actionNeeded: true },
  { key: "low_stock", label: "Out of stock", actionNeeded: true },
  { key: "pending_prints", label: "Pending prints", actionNeeded: false },
  { key: "active_prints", label: "Active prints", actionNeeded: false },
  { key: "prints_awaiting_collection", label: "Ready to collect", actionNeeded: false },
  { key: "failed_emails", label: "Failed emails", actionNeeded: true },
  { key: "stocktakes_awaiting_approval", label: "Stocktakes awaiting approval", actionNeeded: true },
  { key: "warranty_expiring", label: "Warranties expiring", actionNeeded: true },
  { key: "maintenance_overdue", label: "Maintenance overdue", actionNeeded: true },
  { key: "pending_payments", label: "Pending payments", actionNeeded: true },
];

const MACHINE_TILE_KEYS = new Set<Tile["key"]>([
  "pending_prints",
  "active_prints",
  "prints_awaiting_collection",
  "warranty_expiring",
  "maintenance_overdue",
]);

export function DashboardPanel({ makerspace, canManageMakerspace }: { makerspace: Makerspace; canManageMakerspace: boolean }) {
  const dashboard = useStaffGet<DashboardCounts>(
    ["dashboard", makerspace.id],
    `/admin/makerspace/${makerspace.id}/dashboard`,
  );

  return (
    <Panel title="Dashboard">
      {dashboard.isLoading ? <p className="mb-3 text-sm text-muted">Loading dashboard...</p> : null}
      {dashboard.error ? <p className="mb-3 text-sm text-danger">{dashboard.error.message}</p> : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {TILES.filter((tile) => (
          (dashboard.data?.scope_mode !== "machine" || MACHINE_TILE_KEYS.has(tile.key))
          && (tile.key !== "pending_payments" || canManageMakerspace)
        )).map((tile) => {
          const value = dashboard.data?.[tile.key] ?? 0;
          const needsAttention = tile.actionNeeded && value > 0;
          return (
            <div
              key={tile.key}
              className={`status-box flex min-h-24 flex-col items-start justify-center gap-1 p-4 ${needsAttention ? "status-box-danger" : ""}`}
            >
              <span className={`text-3xl font-semibold ${needsAttention ? "text-danger" : ""}`}>
                {value}
              </span>
              <span className="text-sm text-muted">{tile.label}</span>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
