import { useMutation, useQueryClient } from "@tanstack/react-query";

import { StatusBadge } from "../../components/ui";
import {
  invalidatePaymentViews,
  reconcilePayment,
} from "./paymentsApi";

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
  const mutation = useMutation({
    mutationFn: (action: "mark-offline" | "waive") =>
      reconcilePayment(makerspaceId, action, [payment!.id], false),
    onSuccess: () => {
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
            onClick={() => mutation.mutate("mark-offline")}
          >
            Mark offline
          </button>
          <button
            className="desk-button-warn"
            type="button"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate("waive")}
          >
            Waive
          </button>
        </>
      ) : null}
      {mutation.error ? (
        <span className="text-danger" role="alert">{mutation.error.message}</span>
      ) : null}
    </div>
  );
}
