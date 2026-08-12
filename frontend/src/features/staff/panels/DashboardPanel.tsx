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

// Each tile carries a palette tone, so the grid speaks the whole four-colour system instead
// of reading as a wall of neutral boxes with one alarming red one. The tone is chosen by what
// the number MEANS -- it is varied, not arbitrary: `danger` is reserved for things that are
// actually wrong, `warn` for a queue somebody has to work through, `accent` for work in
// flight, `success` for something finished and waiting to be handed over, and `secondary` for
// money. Assigning tones at random would make the colour meaningless and would clash with the
// semantic status colours used everywhere else in the console.
type Tone = "accent" | "secondary" | "success" | "warn" | "danger";

type Tile = {
  key: Exclude<keyof DashboardCounts, "scope_mode">;
  label: string;
  actionNeeded: boolean;
  tone: Tone;
};

const TILES: Tile[] = [
  { key: "overdue_loans", label: "Overdue loans", actionNeeded: true, tone: "danger" },
  { key: "pending_requests", label: "Pending requests", actionNeeded: true, tone: "warn" },
  { key: "awaiting_issue", label: "Awaiting issue", actionNeeded: true, tone: "warn" },
  { key: "open_problem_reports", label: "Problem reports", actionNeeded: true, tone: "danger" },
  { key: "low_stock", label: "Out of stock", actionNeeded: true, tone: "danger" },
  { key: "pending_prints", label: "Pending prints", actionNeeded: false, tone: "warn" },
  { key: "active_prints", label: "Active prints", actionNeeded: false, tone: "accent" },
  { key: "prints_awaiting_collection", label: "Ready to collect", actionNeeded: false, tone: "success" },
  { key: "failed_emails", label: "Failed emails", actionNeeded: true, tone: "danger" },
  { key: "stocktakes_awaiting_approval", label: "Stocktakes awaiting approval", actionNeeded: true, tone: "warn" },
  { key: "warranty_expiring", label: "Warranties expiring", actionNeeded: true, tone: "warn" },
  { key: "maintenance_overdue", label: "Maintenance overdue", actionNeeded: true, tone: "danger" },
  { key: "pending_payments", label: "Pending payments", actionNeeded: true, tone: "secondary" },
];

// Two states per tone, and the INK is the whole point.
//
// `fill` is used only when the tile is calling for attention. Its text colours are the FIXED
// `on-*` tokens, because they sit on a solid pastel and must not go light in dark mode -- the
// previous version put `text-danger` on `bg-danger` (dark red on red, so the number was
// invisible) and left the label at `text-muted` (grey on red). That is the tile in the
// screenshot: not a colour choice, an unreadable one.
//
// `rest` keeps the tile neutral and carries the tone in THE NUMBER ITSELF, which is the piece
// of the tile that actually means something. A thick coloured left edge was tried first and
// removed: a side-tab accent border is a generated-UI cliche, and colouring a rule beside the
// data is weaker than colouring the data. Every `rest` value is an `-ink` token, all of which
// the contrast guard holds at AA against `bg`/`surface`/`panel`.
const TONE_STYLES: Record<Tone, { fill: string; label: string; rest: string }> = {
  accent: { fill: "border-accent bg-accent", label: "text-on-accent/75", rest: "text-accent-ink" },
  secondary: { fill: "border-secondary bg-secondary", label: "text-on-secondary/75", rest: "text-secondary-ink" },
  success: { fill: "border-success bg-success", label: "text-on-success/75", rest: "text-success-ink" },
  warn: { fill: "border-warn bg-warn", label: "text-on-warn/75", rest: "text-warn-ink" },
  // `danger` is the one non-pastel, so it takes the light-on-dark treatment instead of an
  // `on-*` token -- 164 36 59 against `--color-bg` is a wide margin in both themes.
  danger: { fill: "border-danger bg-danger", label: "text-bg/80", rest: "text-danger" },
};

const FILL_INK: Record<Tone, string> = {
  accent: "text-on-accent",
  secondary: "text-on-secondary",
  success: "text-on-success",
  warn: "text-on-warn",
  danger: "text-bg",
};

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
          const tone = TONE_STYLES[tile.tone];
          return (
            <div
              key={tile.key}
              className={`flex min-h-24 flex-col items-start justify-center gap-1 rounded-lg border p-4 shadow-soft ${
                needsAttention ? tone.fill : "border-line bg-panel"
              }`}
            >
              <span className={`font-mono text-3xl font-semibold ${needsAttention ? FILL_INK[tile.tone] : tone.rest}`}>
                {value}
              </span>
              <span className={`eyebrow ${needsAttention ? tone.label : ""}`}>{tile.label}</span>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
