import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { BulkActionToolbar, DataTable, type DataTableColumn } from "../../components/ui";
import { StructuredApiError, staffRequest } from "../../lib/api";
import {
  PAYMENT_STATUSES,
  PAYMENT_SUBJECTS,
  amendSettlement,
  formatMoney,
  invalidatePaymentViews,
  paymentListKey,
  paymentListPath,
  reconcilePayment,
  settlementLabel,
  type PaymentRow,
  type Settlement,
} from "./paymentsApi";
import { PaymentRefundDialog } from "./PaymentRefundDialog";
import { SettlementDialog } from "./SettlementDialog";
import { Panel } from "./panels/shared";
import { paymentAccess } from "./paymentAccess";

type Action = "mark-offline" | "waive";

export function PaymentsPanel({ makerspaceId, actorActions = [], isSuperadmin = false }: {
  makerspaceId: number; actorActions?: readonly string[]; isSuperadmin?: boolean;
}) {
  const forRecording = !isSuperadmin && !actorActions.includes("view_finance");
  const access = (row: PaymentRow) => paymentAccess(actorActions, isSuperadmin, row);
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("pending");
  const [subject, setSubject] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [conflict, setConflict] = useState("");
  const [refundRow, setRefundRow] = useState<PaymentRow | null>(null);
  const payments = useQuery({
    queryKey: paymentListKey(makerspaceId, status, subject, forRecording),
    queryFn: () => staffRequest<PaymentRow[]>(paymentListPath(makerspaceId, status, subject, forRecording)),
  });
  // Marking paid offline is a two-step now: the API requires a receipt, so the click
  // opens the form rather than firing the mutation.
  const [settling, setSettling] = useState<{ ids: number[]; bulk: boolean } | null>(null);
  // A receipt correction appends a new receipt; the payment itself stays settled.
  const [amending, setAmending] = useState<PaymentRow | null>(null);
  const amend = useMutation({
    mutationFn: ({ id, settlement }: { id: number; settlement: Settlement }) =>
      amendSettlement(makerspaceId, id, settlement),
    onSuccess: () => {
      setAmending(null);
      invalidatePaymentViews(queryClient, makerspaceId);
    },
  });
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
    {
      key: "settlement",
      header: "Received",
      render: (row) => row.settlement
        ? `${settlementLabel(row.settlement)}${row.settlement.corrected ? " (corrected)" : ""}`
        : "—",
    },
    { key: "created_at", header: "Created", render: (row) => new Date(row.created_at).toLocaleString() },
    {
      key: "actions",
      header: "Actions",
      render: (row) => (
        <div className="flex flex-wrap gap-2">
          {/* Only a pending charge can be settled or waived; offering it on a settled row
              could only ever answer 409. */}
          {row.status === "pending" ? (
            <>
              {access(row).record ? <button className="desk-button" type="button" disabled={mutation.isPending} onClick={() => run("mark-offline", [row.id], false)}>
                Mark offline
              </button> : null}
              {access(row).waive ? <button className="desk-button" type="button" disabled={mutation.isPending} onClick={() => run("waive", [row.id], false)}>
                Waive
              </button> : null}
            </>
          ) : null}
          {row.status === "paid_offline" && row.settlement && access(row).record ? (
            <button className="desk-button" type="button" disabled={amend.isPending} onClick={() => setAmending(row)}>
              Correct receipt
            </button>
          ) : null}
          {(row.status === "paid_online" || row.status === "paid_offline") && access(row).refund ? (
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
            {PAYMENT_STATUSES.filter(([value]) => !forRecording || ["pending", "paid_offline"].includes(value)).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
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
            {selected.length > 0 && selected.every((id) => payments.data?.some((row) => row.id === id && row.status === "pending" && access(row).record)) ? <button className="desk-button" type="button" disabled={mutation.isPending} onClick={() => run("mark-offline", selected, true)}>Mark offline</button> : null}
            {selected.length > 0 && selected.every((id) => payments.data?.some((row) => row.id === id && row.status === "pending" && access(row).waive)) ? <button className="desk-button" type="button" disabled={mutation.isPending} onClick={() => run("waive", selected, true)}>Waive</button> : null}
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
      {amending ? (
        <SettlementDialog
          count={1}
          pending={amend.isPending}
          title="Correct the receipt"
          onCancel={() => { setAmending(null); amend.reset(); }}
          onConfirm={(settlement) => amend.mutate({ id: amending.id, settlement })}
        />
      ) : null}
      {amend.error ? <p role="alert" className="mb-3 text-sm text-danger">{amend.error.message}</p> : null}
      {conflict ? <p role="alert" className="my-3 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{conflict}</p> : null}
      {payments.error && !payments.data ? <p className="mb-3 text-sm text-danger">{payments.error.message}</p> : null}
      {mutation.error && !conflict ? <p role="alert" className="mb-3 text-sm text-danger">{mutation.error.message}</p> : null}
      <DataTable
        columns={columns}
        data={payments.data ?? []}
        loading={payments.isLoading}
        skeletonCols={8}
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
