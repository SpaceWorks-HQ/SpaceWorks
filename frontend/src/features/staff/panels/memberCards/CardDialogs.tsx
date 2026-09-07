import { Field, Modal } from "../../../../components/ui";
import { REISSUE_REASONS, type MemberCard, type ReissueReason } from "./types";

export function ReissueCardDialog({
  card,
  reason,
  pending,
  error,
  onReasonChange,
  onClose,
  onSubmit,
}: {
  card: MemberCard | null;
  reason: ReissueReason;
  pending: boolean;
  error?: string;
  onReasonChange: (reason: ReissueReason) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  return (
    <Modal
      open={Boolean(card)}
      onClose={onClose}
      title="Reissue card"
      footer={
        <div className="desk-actions flex flex-wrap justify-end gap-2">
          <button className="desk-button" type="button" disabled={pending} onClick={onClose}>
            Cancel
          </button>
          <button className="desk-button-primary" type="button" disabled={pending} onClick={onSubmit}>
            {pending ? "Reissuing…" : "Reissue"}
          </button>
        </div>
      }
    >
      <p className="text-sm text-muted">
        Replaces <span className="font-mono">{card?.card_number}</span> for {card?.printed_name}. The
        old card stops resolving as soon as the new one is issued.
      </p>
      <Field label="Reason" className="mt-3">
        <select
          className="desk-input"
          value={reason}
          onChange={(event) => onReasonChange(event.target.value as ReissueReason)}
        >
          {REISSUE_REASONS.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </Field>
      {error ? (
        <p className="mt-3 text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </Modal>
  );
}

export function RevokeCardDialog({
  card,
  reason,
  pending,
  error,
  onReasonChange,
  onClose,
  onSubmit,
}: {
  card: MemberCard | null;
  reason: string;
  pending: boolean;
  error?: string;
  onReasonChange: (reason: string) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  return (
    <Modal
      open={Boolean(card)}
      onClose={onClose}
      title="Revoke card"
      footer={
        <div className="desk-actions flex flex-wrap justify-end gap-2">
          <button className="desk-button" type="button" disabled={pending} onClick={onClose}>
            Cancel
          </button>
          <button className="desk-button-danger" type="button" disabled={pending} onClick={onSubmit}>
            {pending ? "Revoking…" : "Revoke card"}
          </button>
        </div>
      }
    >
      <p className="text-sm text-muted">
        Revoke <span className="font-mono">{card?.card_number}</span> for {card?.printed_name}? It
        will stop resolving at the door, and its photo is deleted.
      </p>
      <Field label="Reason (optional)" className="mt-3">
        <input
          className="desk-input"
          value={reason}
          onChange={(event) => onReasonChange(event.target.value)}
        />
      </Field>
      {error ? (
        <p className="mt-3 text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </Modal>
  );
}
