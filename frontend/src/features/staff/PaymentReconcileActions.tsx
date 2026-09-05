import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { StatusBadge } from "../../components/ui";
import {
  invalidatePaymentViews,
  reconcilePayment,
  type Settlement,
} from "./paymentsApi";
import { SettlementDialog } from "./SettlementDialog";

export type PaymentSummary = {
  id: number;
  status: "pending" | "paid_online" | "paid_offline" | "waived" | "canceled";
  amount: string;
  currency: string;
};

export function PaymentReconcileActions({
  makerspaceId,
  payment,
  invalidateKeys = [],
}: {
  makerspaceId: number;
  payment: PaymentSummary | null;
  invalidateKeys?: readonly (readonly unknown[])[];
}) {
  const queryClient = useQueryClient();
  // Marking paid offline needs the receipt the API requires, so the button opens the
  // form rather than settling straight away.
  const [settling, setSettling] = useState(false);
  const mutation = useMutation({
    mutationFn: ({ action, settlement }: {
      action: "mark-offline" | "waive"; settlement?: Settlement;
    }) => reconcilePayment(makerspaceId, action, [payment!.id], false, settlement),
    onSuccess: () => {
      setSettling(false);
      invalidatePaymentViews(queryClient, makerspaceId);
      for (const queryKey of invalidateKeys) {
        queryClient.invalidateQueries({ queryKey });
      }
    },
  });

  if (!payment) return null;
  const amount = new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: payment.currency.toUpperCase(),
  }).format(Number(payment.amount));
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
      <span className="font-mono font-semibold text-ink">Payment {amount}</span>
      <StatusBadge status={payment.status} />
      {payment.status === "pending" ? (
        <>
          <button
            className="desk-button-success"
            type="button"
            disabled={mutation.isPending}
            onClick={() => setSettling(true)}
          >
            Mark offline
          </button>
          <button
            className="desk-button-warn"
            type="button"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate({ action: "waive" })}
          >
            Waive
          </button>
        </>
      ) : null}
      {mutation.error ? (
        <span className="text-danger" role="alert">{mutation.error.message}</span>
      ) : null}
      {settling ? (
        <div className="w-full">
          <SettlementDialog
            count={1}
            pending={mutation.isPending}
            onCancel={() => setSettling(false)}
            onConfirm={(settlement) =>
              mutation.mutate({ action: "mark-offline", settlement })
            }
          />
        </div>
      ) : null}
    </div>
  );
}
