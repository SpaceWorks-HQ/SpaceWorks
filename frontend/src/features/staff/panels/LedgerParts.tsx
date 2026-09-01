import { Skeleton, SkeletonRows } from "../../../components/ui";

export type LedgerSource = "request" | "self_checkout" | "direct_handout";
export type LedgerSourceFilter = "" | "reviewed" | "self_checkout" | "direct";

export type LedgerRow = {
  source: LedgerSource;
  item_name: string;
  container: string | null;
  units: Array<{ asset_tag: string; serial_number: string }>;
  target_label: string | null;
  holder: string;
  quantity: number;
  since: string | null;
  due: string | null;
  makerspace_id: number;
  reference_id: number;
  status: string;
};

export type LedgerResponse = {
  count: number;
  results: LedgerRow[];
};

export type SortKey = "item_name" | "holder" | "quantity" | "since" | "due" | "source" | "makerspace_id";
export type SortDirection = "asc" | "desc";

export const sourceLabels: Record<LedgerSource, string> = {
  request: "Request",
  self_checkout: "Self-checkout",
  direct_handout: "Direct",
};

export function LedgerSkeleton({ aggregate }: { aggregate: boolean }) {
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="min-w-[760px] divide-y divide-line text-left text-sm" aria-hidden="true">
        <thead className="eyebrow bg-bg">
          <tr>
            {["Item", "Holder", "Qty", "Out since", "Due", "Source", aggregate ? "Makerspace" : ""]
              .filter(Boolean)
              .map((label) => (
                <th scope="col" key={label} className="whitespace-nowrap px-3 py-2">
                  <Skeleton className="h-3 w-20" />
                </th>
              ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line bg-surface">
          <SkeletonRows rows={4} cols={aggregate ? 7 : 6} />
        </tbody>
      </table>
    </div>
  );
}

export function UnitLines({ row }: { row: LedgerRow }) {
  if (row.units.length) {
    return (
      <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-xs text-muted">
        {row.units.map((unit) => (
          <span className="break-words" key={`${unit.asset_tag}-${unit.serial_number || "no-serial"}`}>
            #{unit.asset_tag}
            {unit.serial_number ? ` - ${unit.serial_number}` : ""}
          </span>
        ))}
      </div>
    );
  }

  return row.target_label ? <div className="mt-0.5 break-words text-xs text-muted">{row.target_label}</div> : null;
}

export function SortableHeader({
  label,
  sortKey,
  sort,
  onSort,
  align = "left",
}: {
  label: string;
  sortKey: SortKey;
  sort: { key: SortKey; direction: SortDirection };
  onSort: (key: SortKey) => void;
  align?: "left" | "right";
}) {
  const active = sort.key === sortKey;
  return (
    <th scope="col" className={`whitespace-nowrap px-3 py-2 ${align === "right" ? "text-right" : "text-left"}`}>
      <button
        type="button"
        className={`desk-button-ghost ${align === "right" ? "justify-end" : ""}`}
        onClick={() => onSort(sortKey)}
      >
        {label}
        <span className="text-[10px]">{active ? (sort.direction === "asc" ? "^" : "v") : "-"}</span>
      </button>
    </th>
  );
}

export function ledgerParams({
  page,
  pageSize,
  search,
  source,
  overdueOnly,
  sort,
}: {
  page?: number;
  pageSize?: number;
  search: string;
  source: LedgerSourceFilter;
  overdueOnly: boolean;
  sort: string;
}) {
  const params = new URLSearchParams();
  if (page) params.set("page", String(page));
  if (pageSize) params.set("page_size", String(pageSize));
  const trimmed = search.trim();
  if (trimmed) params.set("search", trimmed);
  if (source) params.set("source", source);
  if (overdueOnly) params.set("overdue", "true");
  params.set("sort", sort);
  return params;
}

export function isOverdue(value: string | null, now: number) {
  return Boolean(value && new Date(value).getTime() < now);
}

export function formatDate(value: string | null) {
  if (!value) return "\u2014";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "\u2014";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
