import { useEffect, useState } from "react";
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
import { useUrlListState } from "../../lib/useUrlListState";
import type { Paginated } from "../../lib/usePaginatedQuery";
import { Pagination } from "../../components/ui/Pagination";
import { ListViewControls } from "./ListViewControls";
import { Panel } from "./panels/shared";
import { paymentAccess } from "./paymentAccess";
import { DUE_OPTIONS, PaymentDueBadge } from "./PaymentDueBadge";
import { RefundReceiptAmendDialog } from "./RefundReceiptAmendDialog";
import type { RefundRow } from "./paymentsApi";
import { PaymentDocuments } from "../payments/PaymentDocuments";

type Action = "mark-offline" | "waive";

export function PaymentsPanel({ makerspaceId, actorActions = [], isSuperadmin = false }: {
  makerspaceId: number; actorActions?: readonly string[]; isSuperadmin?: boolean;
}) {
  const forRecording = !isSuperadmin && !actorActions.includes("view_finance");
  const access = (row: PaymentRow) => paymentAccess(actorActions, isSuperadmin, row);
  const queryClient = useQueryClient();
  const list = useUrlListState({ status: "pending", subject_type: "", due_state: "", ordering: "due_at", page: "1" });
  const status = list.values.status;
  const subject = list.values.subject_type;
  const dueState = list.values.due_state;
  const [correctingRefund, setCorrectingRefund] = useState<{ paymentId: number; refund: RefundRow } | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [conflict, setConflict] = useState("");
  const [refundRow, setRefundRow] = useState<PaymentRow | null>(null);
  const payments = useQuery({
    queryKey: [...paymentListKey(makerspaceId, status, subject, forRecording, dueState), list.page, list.values.ordering],
    queryFn: () => staffRequest<Paginated<PaymentRow>>(paymentListPath(makerspaceId, status, subject, forRecording, dueState) + `${status || subject || forRecording || dueState ? "&" : "?"}page=${list.page}&ordering=${encodeURIComponent(list.values.ordering)}`),
  });
  useEffect(() => { setSelected([]); }, [makerspaceId, list.query]);
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
    { key: "subject_label", header: "Subject" },
    { key: "subject_type", header: "Type", render: (row) => labelFor(PAYMENT_SUBJECTS, row.subject_type) },
    { key: "status", header: "Status", render: (row) => labelFor(PAYMENT_STATUSES, row.status) },
    { key: "due_at", header: "Due", render: (row) => <PaymentDueBadge payment={row} /> },
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
              {row.subject_type === "loan_deposit" && row.status === "paid_offline" ? "Release deposit" : "Refund"}
            </button>
          ) : null}
          {row.refunds?.filter((refund) => refund.provider === "manual" && !refund.corrected).map((refund) =>
            access(row).refund ? <button key={refund.id} className="desk-button" type="button"
              onClick={() => setCorrectingRefund({ paymentId: row.id, refund })}>Correct refund #{refund.id}</button> : null)}
        </div>
      ),
    },
  ];

  return (
    <Panel title="Payments">
      {!forRecording ? <PaymentDocuments key={makerspaceId} makerspaceId={makerspaceId} audience="staff" /> : null}
      <ListViewControls state={list} makerspaceId={makerspaceId} entity="payments" search={false} sorts={[["due_at", "Due date"], ["-due_at", "Due date descending"], ["-created_at", "Newest"], ["created_at", "Oldest"], ["amount", "Amount ascending"], ["-amount", "Amount descending"]]} />
      <div className="mb-3 flex flex-wrap gap-3">
        <label className="grid gap-1 text-xs text-muted"><span>Due</span>
          <select className="desk-input" value={dueState} onChange={(event) => { list.update({ due_state: event.target.value, ...(event.target.value ? { status: "pending" } : {}) }); }}>
            <option value="">All due dates</option>{DUE_OPTIONS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-xs text-muted">
          <span>Status</span>
          <select className="desk-input" value={status} onChange={(event) => { list.update({ status: event.target.value, ...(event.target.value !== "pending" ? { due_state: "" } : {}) }); }}>
            <option value="">All statuses</option>
            {PAYMENT_STATUSES.filter(([value]) => !forRecording || ["pending", "paid_offline"].includes(value)).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-xs text-muted">
          <span>Subject</span>
          <select className="desk-input" value={subject} onChange={(event) => { list.setFilter("subject_type", event.target.value); }}>
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
            {selected.length > 0 && selected.every((id) => payments.data?.results.some((row) => row.id === id && row.status === "pending" && access(row).record)) ? <button className="desk-button" type="button" disabled={mutation.isPending} onClick={() => run("mark-offline", selected, true)}>Mark offline</button> : null}
            {selected.length > 0 && selected.every((id) => payments.data?.results.some((row) => row.id === id && row.status === "pending" && access(row).waive)) ? <button className="desk-button" type="button" disabled={mutation.isPending} onClick={() => run("waive", selected, true)}>Waive</button> : null}
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
        listState={list}
        columns={columns}
        data={payments.data?.results ?? []}
        loading={payments.isLoading}
        skeletonCols={8}
        selectedIds={selected}
        onSelectionChange={(ids) => setSelected(ids.map(Number))}
        emptyTitle="No matching payments"
      />
      <Pagination page={list.page} totalPages={Math.max(1, Math.ceil((payments.data?.count ?? 0) / 24))} count={payments.data?.count ?? 0} pageSize={24} onChange={list.setPage} />
      {refundRow ? (
        <PaymentRefundDialog
          key={refundRow.id}
          makerspaceId={makerspaceId}
          payment={refundRow}
          releaseDeposit={refundRow.subject_type === "loan_deposit" && refundRow.status === "paid_offline"}
          onClose={() => setRefundRow(null)}
        />
      ) : null}
      {correctingRefund ? <RefundReceiptAmendDialog makerspaceId={makerspaceId}
        paymentId={correctingRefund.paymentId} refund={correctingRefund.refund}
        onClose={() => setCorrectingRefund(null)} /> : null}
    </Panel>
  );
}

function labelFor(options: readonly (readonly [string, string])[], value: string) {
  return options.find(([key]) => key === value)?.[1] ?? value.replace(/_/g, " ");
}
