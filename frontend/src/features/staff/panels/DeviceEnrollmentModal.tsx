import { useState } from "react";
import { Modal } from "../../../components/ui";
import type { EnrollmentGrant } from "../devicesApi";

export function DeviceEnrollmentModal({ grant, onClose }: { grant: EnrollmentGrant; onClose: () => void }) {
  const [copyState, setCopyState] = useState("");
  return <Modal open title="One-time device enrollment" onClose={onClose} footer={
    <button className="desk-button" onClick={onClose}>Close and discard token</button>
  }>
    <p>Copy this bearer token to the device now. Closing discards it; it cannot be read again.</p>
    <p>Purpose: {grant.purpose} | Expires: {grant.expires_at}</p>
    <label>Enrollment identifier<input className="desk-input block w-full" readOnly value={grant.enrollment_id} /></label>
    <label>Enrollment token<textarea className="desk-input block w-full" readOnly value={grant.token} /></label>
    <button className="desk-button mt-3" onClick={async () => {
      try { await navigator.clipboard.writeText(JSON.stringify(grant)); setCopyState("Enrollment copied. Clear your clipboard after use."); }
      catch { setCopyState("Copy unavailable. Select and copy the identifier and token manually."); }
    }}>Copy enrollment</button>
    <p role="status">{copyState}</p>
  </Modal>;
}
