import type { Key } from "react";

import { Badge, DataTable, type DataTableColumn } from "../../../../components/ui";
import type { CardStatus, MemberCard } from "./types";

function shortDate(value: string | null) {
  if (!value) return "never";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString();
}

export function CardsTable({
  cards,
  status,
  loading,
  selectedIds,
  onSelectionChange,
  printingCardId,
  onPrint,
  onReissue,
  onRevoke,
}: {
  cards: MemberCard[];
  status: CardStatus;
  loading: boolean;
  selectedIds: number[];
  onSelectionChange: (ids: number[]) => void;
  printingCardId: number | null;
  onPrint: (card: MemberCard) => void;
  onReissue: (card: MemberCard) => void;
  onRevoke: (card: MemberCard) => void;
}) {
  const columns: DataTableColumn<MemberCard>[] = [
    {
      key: "card_number",
      header: "Card number",
      sortable: true,
      render: (card) => <span className="font-mono text-xs">{card.card_number}</span>,
    },
    { key: "printed_name", header: "Name", sortable: true },
    {
      key: "is_active",
      header: "Status",
      render: (card) =>
        card.is_active ? (
          <Badge tone="success">active</Badge>
        ) : (
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone="danger">revoked</Badge>
            {card.revoked_reason ? (
              <span className="text-xs text-muted">{card.revoked_reason}</span>
            ) : null}
          </span>
        ),
    },
    {
      key: "print_count",
      header: "Prints",
      sortable: true,
      render: (card) => (
        <span className="text-xs text-muted">
          <span className="font-mono text-ink">{card.print_count}</span> · last{" "}
          {shortDate(card.last_printed_at)}
        </span>
      ),
    },
    {
      key: "photo_set",
      header: "Photo",
      render: (card) =>
        card.photo_set ? <Badge tone="neutral">on file</Badge> : <span className="text-xs text-muted">none</span>,
    },
    {
      key: "actions",
      header: "Actions",
      render: (card) => (
        <div className="desk-actions flex flex-wrap gap-2">
          <button
            className="desk-button-ghost"
            type="button"
            disabled={printingCardId === card.id}
            onClick={() => onPrint(card)}
          >
            {printingCardId === card.id ? "Preparing…" : "Print"}
          </button>
          {card.is_active ? (
            <>
              <button className="desk-button-ghost" type="button" onClick={() => onReissue(card)}>
                Reissue
              </button>
              <button className="desk-button-ghost text-danger" type="button" onClick={() => onRevoke(card)}>
                Revoke
              </button>
            </>
          ) : null}
        </div>
      ),
    },
  ];

  // Selection only exists on the active list: the sheet endpoint prints active cards, so
  // offering checkboxes on revoked rows would build a selection the print refuses.
  const selection =
    status === "active"
      ? { selectedIds, onSelectionChange: (ids: Key[]) => onSelectionChange(ids.map(Number)) }
      : {};

  return (
    <DataTable
      columns={columns}
      data={cards}
      loading={loading}
      skeletonCols={6}
      emptyTitle={status === "active" ? "No active cards" : "No revoked cards"}
      emptyDescription={
        status === "active"
          ? "Issue a card to a member from the roster below."
          : "Revoked cards stay listed here for the audit trail."
      }
      {...selection}
    />
  );
}
