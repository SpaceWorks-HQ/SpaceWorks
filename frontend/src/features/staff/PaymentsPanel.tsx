import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { BulkActionToolbar, DataTable, type DataTableColumn } from "../../components/ui";
import { StructuredApiError, staffRequest } from "../../lib/api";
import {
  PAYMENT_STATUSES,
  PAYMENT_SUBJECTS,
  formatMoney,
  invalidatePaymentViews,
  paymentListKey,
  paymentListPath,
  reconcilePayment,
  type PaymentRow,
  type Settlement,
} from "./paymentsApi";
import { PaymentRefundDialog } from "./PaymentRefundDialog";
import { SettlementDialog } from "./SettlementDialog";
import { Panel } from "./panels/shared";

type Action = "mark-offline" | "waive";

export function PaymentsPanel({ makerspaceId }: { makerspaceId: number }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("pending");
  const [subject, setSubject] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [conflict, setConflict] = useState("");
  const [refundRow, setRefundRow] = useState<PaymentRow | null>(null);
  const payments = useQuery({
    queryKey: paymentListKey(makerspaceId, status, subject),
    queryFn: () => staffRequest<PaymentRow[]>(paymentListPath(makerspaceId, status, subject)),
  });
  // Marking paid offline is a two-step now: the API requires a receipt, so the click
  // opens the form rather than firing the mutation.
  const [settling, setSettling] = useState<{ ids: number[]; bulk: boolean } | null>(null);
  const mutation = useMutation({
    mutationFn: ({ action, ids, bulk, settlement }: {
      action: Action; ids: number[]; bulk: boolean; settlement?: Settlement;
    }) => reconcilePayment(makerspaceId, action, ids, bulk, settlement),
    onSuccess: () => {
      setConflict("");
      setSelected([]);
      setSettling(null);
      invalidatePaymentViews(queryClient, makerspaceId);
    },
    onError: (error) => {
      if (error instanceof StructuredApiError && error.status === 409) {
        setConflict(error.message || "This payment was already reconciled.");
        void payments.refetch();
      }
    },
  });
  const run = (action: Action, ids: number[], bulk: boolean) => {
    setConflict("");
    if (action === "mark-offline") {
      setSettling({ ids, bulk });
      return;
    }
    mutation.mutate({ action, ids, bulk });
  };
  const columns: DataTableColumn<PaymentRow>[] = [
    { key: "subject_label", header: "Subject", sortable: true },
    { key: "subject_type", header: "Type", render: (row) => labelFor(PAYMENT_SUBJECTS, row.subject_type) },
    { key: "status", header: "Status", render: (row) => labelFor(PAYMENT_STATUSES, row.status) },
    { key: "amount", header: "Amount", render: (row) => formatMoney(row.amount, row.currency), className: "font-semibold" },
    { key: "refunded_amount", header: "Refunded", render: (row) => Number(row.refunded_amount) > 0 ? formatMoney(row.refunded_amount, row.currency) : "—" },
    { key: "created_at", header: "Created", render: (row) => new Date(row.created_at).toLocaleString() },
    {
      key: "actions",
      header: "Actions",
      render: (row) => (
        <div className="flex flex-wrap gap-2">
          <button className="desk-button" type="button" disabled={mutation.isPending} onClick={() => run("mark-offline", [row.id], false)}>
            Mark offline
          </button>
          <button className="desk-button" type="button" disabled={mutation.isPending} onClick={() => run("waive", [row.id], false)}>
            Waive
          </button>
          {row.status === "paid_online" ? (
            <button className="desk-button" type="button" onClick={() => setRefundRow(row)}>
              Refund
            </button>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <Panel title="Payments">
      <div className="mb-3 flex flex-wrap gap-3">
        <label className="grid gap-1 text-xs text-muted">
          <span>Status</span>
          <select className="desk-input" value={status} onChange={(event) => { setStatus(event.target.value); setSelected([]); }}>
            <option value="">All statuses</option>
            {PAYMENT_STATUSES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-xs text-muted">
          <span>Subject</span>
          <select className="desk-input" value={subject} onChange={(event) => { setSubject(event.target.value); setSelected([]); }}>
            <option value="">All subjects</option>
            {PAYMENT_SUBJECTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
      </div>
      <BulkActionToolbar
        selectedCount={selected.length}
        onClear={() => setSelected([])}
        actions={(
          <>
            <button className="desk-button" type="button" disabled={mutation.isPending} onClick={() => run("mark-offline", selected, true)}>Mark offline</button>
            <button className="desk-button" type="button" disabled={mutation.isPending} onClick={() => run("waive", selected, true)}>Waive</button>
          </>
        )}
      />
      {settling ? (
        <SettlementDialog
          count={settling.ids.length}
          pending={mutation.isPending}
          onCancel={() => setSettling(null)}
          onConfirm={(settlement) =>
            mutation.mutate({
              action: "mark-offline",
              ids: settling.ids,
              bulk: settling.bulk,
              settlement,
            })
          }
        />
      ) : null}
      {conflict ? <p role="alert" className="my-3 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{conflict}</p> : null}
      {payments.error && !payments.data ? <p className="mb-3 text-sm text-danger">{payments.error.message}</p> : null}
      {mutation.error && !conflict ? <p role="alert" className="mb-3 text-sm text-danger">{mutation.error.message}</p> : null}
      <DataTable
        columns={columns}
        data={payments.data ?? []}
        loading={payments.isLoading}
        skeletonCols={7}
        selectedIds={selected}
        onSelectionChange={(ids) => setSelected(ids.map(Number))}
        emptyTitle="No matching payments"
      />
      {refundRow ? (
        <PaymentRefundDialog
          key={refundRow.id}
          makerspaceId={makerspaceId}
          payment={refundRow}
          onClose={() => setRefundRow(null)}
        />
      ) : null}
    </Panel>
  );
}

function labelFor(options: readonly (readonly [string, string])[], value: string) {
  return options.find(([key]) => key === value)?.[1] ?? value.replace(/_/g, " ");
}
