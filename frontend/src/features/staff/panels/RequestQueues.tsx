import { StaffLoanRenew } from "../StaffLoanRenew";
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Field } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { Pagination } from "../../../components/ui/Pagination";
import { useDebouncedValue } from "../../../lib/useDebouncedValue";
import { useUrlListState } from "../../../lib/useUrlListState";
import { ListViewControls } from "../ListViewControls";
import { usePaginatedQuery } from "../../../lib/usePaginatedQuery";
import { issueErrorMessage } from "../issueErrors";
import { Panel, type Makerspace } from "./shared";
import { RequestList } from "./QueuesList";
import { PendingActions, AcceptedActions, ActiveActions, HistoryPanel } from "./QueuesDisplay";
import { actionInvalidationScope, invalidateRequestQueues } from "./QueuesInvalidation";
import {
  AssignIssueModal,
  RejectRequestModal,
  ReturnDueModal,
  ReturnRequestModal,
  type AssignIssueValues,
  type RejectRequestValues,
  type ReturnDueValues,
  type ReturnRequestValues,
} from "./QueuesModals";
import { RequestListSkeleton } from "./QueuesSkeleton";
import { AcceptRequestModal } from "./QueuesAcceptModal";

export type RequestItem = {
  id: number;
  product_id: number;
  product_name: string;
  storage_location: string;
  tracking_mode: string;
  requires_asset_qr: boolean;
  requested_quantity: number;
  accepted_quantity: number;
  issued_quantity: number;
  returned_quantity: number;
  damaged_quantity: number;
  missing_quantity: number;
  needs_fix_quantity: number;
  issued_assets?: Array<{ asset_id: number; asset_tag: string; serial_number: string }>;
};
export type HardwareRequest = {
  id: number;
  status: string;
  requester_username: string;
  requester_display?: string;
  requester_contact_email?: string;
  requester_contact_phone?: string;
  rejection_reason?: string;
  issue_evidence_id?: number | null;
  return_evidence_ids?: number[];
  requested_for: string;
  return_due_at: string | null;
  return_reminder_sent_at: string | null;
  items: RequestItem[];
  // AdminRequestSerializer serializes the assigned container as the flat `assigned_box_label`.
  assigned_box_label?: string | null;
  assigned_box?: { code: string; label: string };
};

export function Queues({ makerspace, guestOnly, canViewAudit = false }: { makerspace: Makerspace; guestOnly: boolean; canViewAudit?: boolean }) {
  const queryClient = useQueryClient();
  const [acceptRow, setAcceptRow] = useState<HardwareRequest | null>(null);
  const [dueRow, setDueRow] = useState<HardwareRequest | null>(null);
  const [rejectRow, setRejectRow] = useState<HardwareRequest | null>(null);
  const [assignIssueRow, setAssignIssueRow] = useState<HardwareRequest | null>(null);
  const [returnRow, setReturnRow] = useState<HardwareRequest | null>(null);
  const [modalError, setModalError] = useState("");
  const [defaultLoanDays, setDefaultLoanDays] = useState(String(makerspace.default_loan_days ?? 7));
  const list = useUrlListState({ queue: "", id: "", search: "", ordering: "-created_at", pendingPage: "1", acceptedPage: "1", activePage: "1", historyPage: "1", history: "false" });
  const queue = ["pending", "accepted"].includes(list.values.queue) ? list.values.queue : "";
  const showHistory = list.values.history === "true";
  const search = list.values.search;
  const setSearch = (value: string) => list.setFilter("search", value);
  const debouncedSearch = useDebouncedValue(search);

  const pending = usePaginatedQuery<HardwareRequest>({
    key: ["pending", makerspace.id],
    id: list.values.id,
    page: Number(list.values.pendingPage),
    onPageChange: (page) => list.setPage(page, "pendingPage"),
    ordering: list.values.ordering,
    path: `/admin/makerspace/${makerspace.id}/pending-requests`,
    enabled: !guestOnly && (!queue || queue === "pending"),
    search: debouncedSearch,
    resetKey: String(makerspace.id),
  });
  const accepted = usePaginatedQuery<HardwareRequest>({
    key: ["accepted", makerspace.id],
    id: list.values.id,
    page: Number(list.values.acceptedPage),
    onPageChange: (page) => list.setPage(page, "acceptedPage"),
    ordering: list.values.ordering,
    path: `/admin/makerspace/${makerspace.id}/accepted-requests`,
    enabled: !queue || queue === "accepted",
    search: debouncedSearch,
    resetKey: String(makerspace.id),
  });
  const active = usePaginatedQuery<HardwareRequest>({
    key: ["active", makerspace.id],
    id: list.values.id,
    page: Number(list.values.activePage),
    onPageChange: (page) => list.setPage(page, "activePage"),
    ordering: list.values.ordering,
    path: `/admin/makerspace/${makerspace.id}/active-loans`,
    enabled: !queue,
    search: debouncedSearch,
    resetKey: String(makerspace.id),
  });
  const history = usePaginatedQuery<HardwareRequest>({
    key: ["request-history", makerspace.id],
    id: list.values.id,
    page: Number(list.values.historyPage),
    onPageChange: (page) => list.setPage(page, "historyPage"),
    ordering: list.values.ordering,
    path: `/admin/makerspace/${makerspace.id}/request-history`,
    enabled: showHistory && !queue,
    search: debouncedSearch,
    resetKey: String(makerspace.id),
  });

  const action = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: object }) => staffRequest(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
    onSuccess: (_data, { path }) => invalidateRequestQueues(queryClient, makerspace.id, actionInvalidationScope(path)),
  });
  useEffect(() => {
    setDefaultLoanDays(String(makerspace.default_loan_days ?? 7));
  }, [makerspace.default_loan_days, makerspace.id]);

  const openModal = (setter: (row: HardwareRequest | null) => void, row: HardwareRequest) => {
    setModalError("");
    setter(row);
  };
  const closeModals = () => {
    if (action.isPending) return;
    setAcceptRow(null);
    setDueRow(null);
    setRejectRow(null);
    setAssignIssueRow(null);
    setReturnRow(null);
    setModalError("");
  };
  const runAction = async (path: string, body?: object, onDone = closeModals) => {
    setModalError("");
    try {
      await action.mutateAsync({ path, body });
      onDone();
    } catch (error) {
      setModalError(error instanceof Error ? error.message : "Action failed.");
    }
  };
  const submitReturnDue = (values: ReturnDueValues) => {
    if (dueRow) void runAction(`/admin/requests/${dueRow.id}/return-due`, { return_due_at: values.returnDueAt ? new Date(values.returnDueAt).toISOString() : null });
  };
  const submitAccept = (acceptedQuantities: { item_id: number; quantity: number }[]) => {
    if (acceptRow) void runAction(`/admin/requests/${acceptRow.id}/accept`, { accepted_quantities: acceptedQuantities });
  };
  const submitReject = (values: RejectRequestValues) => {
    if (rejectRow) void runAction(`/admin/requests/${rejectRow.id}/reject`, { reason: values.reason });
  };
  const submitReturn = (values: ReturnRequestValues) => {
    if (returnRow) void runAction(`/admin/requests/${returnRow.id}/return`, { evidence_id: values.evidenceId, box_code: values.boxCode, remark: values.remark, resolutions: values.resolutions });
  };
  const submitAssignIssue = async (values: AssignIssueValues) => {
    if (!assignIssueRow) return;
    setModalError("");
    let boxAssigned = false;
    try {
      await action.mutateAsync({ path: `/admin/requests/${assignIssueRow.id}/assign-box`, body: { box_code: values.boxCode } });
      boxAssigned = true;
      await action.mutateAsync({
        path: `/admin/requests/${assignIssueRow.id}/issue`,
        body: { evidence_id: values.evidenceId, remark: values.remark, rejects: values.rejects, asset_qr_payloads: values.assetQrPayloads },
      });
      closeModals();
    } catch (error) {
      const message = issueErrorMessage(error);
      setModalError(boxAssigned ? `Box assigned, but issue failed: ${message} The request still needs the issue step; retry with the assigned box.` : message);
    }
  };

  return (
    <div className="grid gap-4">
      {queue ? <button className="desk-button-ghost w-fit" type="button" onClick={() => list.setFilter("queue", "")}>Show all request queues</button> : null}
      <ListViewControls state={list} makerspaceId={makerspace.id} entity="requests" search={false} sorts={[["-created_at", "Newest"], ["created_at", "Oldest"], ["return_due_at", "Due first"]]} />
      <Field label="Search requests"><input className="desk-input" placeholder="Search requester name, email, phone, or purpose" value={search} onChange={(event) => setSearch(event.target.value)} /></Field>
      {!guestOnly && (!queue || queue === "pending") ? (
        <Panel title="Pending review">
          {pending.isLoading ? <RequestListSkeleton /> : <RequestList rows={pending.results} canViewAudit={canViewAudit} actions={(row) => <PendingActions row={row} disabled={action.isPending} openModal={openModal} setAcceptRow={setAcceptRow} setRejectRow={setRejectRow} setDueRow={setDueRow} />} />}
          <Pagination page={pending.page} totalPages={pending.totalPages} onChange={pending.setPage} count={pending.count} pageSize={pending.pageSize} />
          {pending.error instanceof Error ? <p className="mt-2 text-sm text-danger">{pending.error.message}</p> : null}
        </Panel>
      ) : null}
      {!queue || queue === "accepted" ? <Panel title="Ready for handover">
        {accepted.isLoading ? <RequestListSkeleton /> : <RequestList rows={accepted.results} canViewAudit={canViewAudit} actions={(row) => <AcceptedActions row={row} disabled={action.isPending} openModal={openModal} setAssignIssueRow={setAssignIssueRow} setDueRow={setDueRow} />} />}
        <Pagination page={accepted.page} totalPages={accepted.totalPages} onChange={accepted.setPage} count={accepted.count} pageSize={accepted.pageSize} />
        {accepted.error instanceof Error ? <p className="mt-2 text-sm text-danger">{accepted.error.message}</p> : null}
      </Panel> : null}
      {!guestOnly && !queue ? (
        <Panel title="Active loans">
          {active.isLoading ? <RequestListSkeleton /> : <RequestList rows={active.results} canViewAudit={canViewAudit} actions={(row) => <><ActiveActions row={row} disabled={action.isPending} openModal={openModal} setDueRow={setDueRow} setReturnRow={setReturnRow} />{makerspace.enabled_features?.includes("loans.renewals") ? <StaffLoanRenew makerspaceId={makerspace.id} requestId={row.id} /> : null}</>} />}
          <Pagination page={active.page} totalPages={active.totalPages} onChange={active.setPage} count={active.count} pageSize={active.pageSize} />
          {active.error instanceof Error ? <p className="mt-2 text-sm text-danger">{active.error.message}</p> : null}
        </Panel>
      ) : null}
      {!queue ? <HistoryPanel show={showHistory && !queue} loading={history.isLoading} rows={history.results} page={history.page} totalPages={history.totalPages} count={history.count} pageSize={history.pageSize} canViewAudit={canViewAudit} onPageChange={history.setPage} onToggle={() => list.setFilter("history", String(!showHistory))} /> : null}
      <AcceptRequestModal row={acceptRow} open={Boolean(acceptRow)} pending={action.isPending} error={modalError} onClose={closeModals} onSubmit={submitAccept} />
      <ReturnDueModal row={dueRow} defaultValue={dueRow?.return_due_at ? localDateTimeValue(dueRow.return_due_at) : localDateTimeValue(defaultDueDate(Number(defaultLoanDays) || 7).toISOString())} open={Boolean(dueRow)} pending={action.isPending} error={modalError} onClose={closeModals} onSubmit={submitReturnDue} />
      <RejectRequestModal row={rejectRow} open={Boolean(rejectRow)} pending={action.isPending} error={modalError} onClose={closeModals} onSubmit={submitReject} />
      <AssignIssueModal row={assignIssueRow} open={Boolean(assignIssueRow)} pending={action.isPending} error={modalError} onClose={closeModals} onSubmit={submitAssignIssue} makerspaceId={makerspace.id} />
      <ReturnRequestModal row={returnRow} open={Boolean(returnRow)} pending={action.isPending} error={modalError} onClose={closeModals} onSubmit={submitReturn} makerspaceId={makerspace.id} />
    </div>
  );
}

function defaultDueDate(days: number) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date;
}

function localDateTimeValue(value: string) {
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}
