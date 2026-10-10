import { useState } from "react";
import { Field, Modal } from "../../components/ui";

export function MembershipReasonDialog({ title, pending, error, onConfirm, onClose }: {
  title: string; pending: boolean; error: string | null;
  onConfirm: (reason: string) => void; onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  return <Modal open title={title} onClose={() => { if (!pending) onClose(); }}>
    <form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); if (reason.trim() && !pending) onConfirm(reason.trim()); }}>
      <p className="text-sm text-muted">Record the reason for this decision. It will remain in the membership history.</p>
      <Field label="Decision reason"><textarea className="desk-input" required value={reason} onChange={(event) => setReason(event.target.value)} /></Field>
      {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
      <div className="flex gap-2"><button className="desk-button" type="button" disabled={pending} onClick={onClose}>Cancel</button>
        <button className="desk-button-primary" type="submit" disabled={pending || !reason.trim()}>{pending ? "Saving…" : "Confirm decision"}</button></div>
    </form>
  </Modal>;
}
