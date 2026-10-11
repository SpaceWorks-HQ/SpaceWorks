import { Pagination } from "../../../components/ui/Pagination";
import { Panel } from "./shared";
import { RequestList } from "./QueuesList";
import type { HardwareRequest } from "./Queues";

export function PendingActions({ row, disabled, openModal, setAcceptRow, setRejectRow, setDueRow }: QueueActionProps & { setAcceptRow: Setter; setRejectRow: Setter; setDueRow: Setter }) {
  return <><button className="desk-button-success" disabled={disabled} onClick={() => openModal(setAcceptRow, row)}>Accept</button><button className="desk-button-danger" disabled={disabled} onClick={() => openModal(setRejectRow, row)}>Reject</button><button className="desk-button-warn" disabled={disabled} onClick={() => openModal(setDueRow, row)}>Set due</button></>;
}

export function AcceptedActions({ row, disabled, openModal, setAssignIssueRow, setDueRow }: QueueActionProps & { setAssignIssueRow: Setter; setDueRow: Setter }) {
  return <><button className="desk-button-primary" disabled={disabled} onClick={() => openModal(setAssignIssueRow, row)}>Assign + issue</button><button className="desk-button-warn" disabled={disabled} onClick={() => openModal(setDueRow, row)}>Set due</button></>;
}

export function ActiveActions({ row, disabled, openModal, setDueRow, setReturnRow }: QueueActionProps & { setDueRow: Setter; setReturnRow: Setter }) {
  return <><button className="desk-button-warn" disabled={disabled} onClick={() => openModal(setDueRow, row)}>Set due</button><button className="desk-button-success" disabled={disabled} onClick={() => openModal(setReturnRow, row)}>Return</button></>;
}

export function HistoryPanel({
  show,
  loading,
  rows,
  page,
  totalPages,
  count,
  pageSize,
  canViewAudit,
  onPageChange,
  onToggle,
}: {
  show: boolean;
  loading: boolean;
  rows: HardwareRequest[];
  page: number;
  totalPages: number;
  count: number;
  pageSize: number;
  canViewAudit: boolean;
  onPageChange: (page: number) => void;
  onToggle: () => void;
}) {
  return (
    <Panel title="History">
      <button type="button" className="desk-button-ghost" onClick={onToggle}>{show ? "Hide history" : "Show history (returned / rejected / closed with issue)"}</button>
      {show ? (
        <div className="mt-3">
          {loading ? <p className="text-sm text-muted">Loading history...</p> : null}
          <RequestList rows={rows} canViewAudit={canViewAudit} actions={() => null} />
          <Pagination page={page} totalPages={totalPages} onChange={onPageChange} count={count} pageSize={pageSize} />
        </div>
      ) : null}
    </Panel>
  );
}

export type Setter = (row: HardwareRequest | null) => void;
type QueueActionProps = { row: HardwareRequest; disabled: boolean; openModal: (setter: Setter, row: HardwareRequest) => void };

