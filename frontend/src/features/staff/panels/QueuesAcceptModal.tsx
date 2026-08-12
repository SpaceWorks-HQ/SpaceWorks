import { useEffect, useState } from "react";

import { Modal } from "../../../components/ui/Modal";
import type { HardwareRequest } from "./Queues";

type AcceptedQuantity = { item_id: number; quantity: number };

export function AcceptRequestModal({
  row,
  open,
  pending,
  error,
  onClose,
  onSubmit,
}: {
  row: HardwareRequest | null;
  open: boolean;
  pending: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (acceptedQuantities: AcceptedQuantity[]) => void;
}) {
  const [quantities, setQuantities] = useState<Record<number, number>>({});

  useEffect(() => {
    if (!open || !row) return;
    // Default to full accept; the manager dials each line down as needed.
    setQuantities(Object.fromEntries(row.items.map((item) => [item.id, item.requested_quantity])));
  }, [open, row]);

  const total = Object.values(quantities).reduce((sum, value) => sum + (Number(value) || 0), 0);
  const canSubmit = total > 0 && !pending;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={row ? `Accept request #${row.id}` : "Accept request"}
      footer={
        <div className="desk-actions flex flex-wrap justify-end gap-2">
          <button className="desk-button-ghost" type="button" disabled={pending} onClick={onClose}>Cancel</button>
          <button className="desk-button-success" type="submit" form="accept-request-form" disabled={!canSubmit}>
            {pending ? "Accepting..." : "Accept"}
          </button>
        </div>
      }
    >
      <form
        id="accept-request-form"
        className="grid gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!row || !canSubmit) return;
          onSubmit(row.items.map((item) => ({ item_id: item.id, quantity: Number(quantities[item.id]) || 0 })));
        }}
      >
        <p className="text-sm text-muted">
          Accept up to the requested quantity per item. Lower a line to approve a partial amount; set 0 to
          decline that item (at least one unit must be accepted).
        </p>
        <div className="grid gap-2">
          {row?.items.map((item) => (
            <label key={item.id} className="grid grid-cols-[1fr_auto] items-center gap-3 rounded-md border border-line p-2 text-sm">
              <span className="min-w-0">
                <span className="font-medium text-ink">{item.product_name}</span>
                <span className="ml-1 text-xs text-muted">(requested {item.requested_quantity})</span>
              </span>
              <input
                className="desk-input w-24"
                type="number"
                min={0}
                max={item.requested_quantity}
                value={quantities[item.id] ?? item.requested_quantity}
                disabled={pending}
                onChange={(event) =>
                  setQuantities((current) => ({
                    ...current,
                    [item.id]: Math.max(0, Math.min(item.requested_quantity, Number(event.target.value) || 0)),
                  }))
                }
              />
            </label>
          ))}
        </div>
        {total === 0 ? <p className="text-xs text-warn-ink">Accept at least one unit, or reject the request instead.</p> : null}
        {error ? <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p> : null}
      </form>
    </Modal>
  );
}
