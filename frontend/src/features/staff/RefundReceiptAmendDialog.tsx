import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Field, Modal } from "../../components/ui";
import { amendRefund, invalidatePaymentViews, SETTLEMENT_METHODS, type RefundRow } from "./paymentsApi";

export function RefundReceiptAmendDialog({ makerspaceId, paymentId, refund, onClose }: {
  makerspaceId: number; paymentId: number; refund: RefundRow; onClose: () => void;
}) {
  const client = useQueryClient();
  const [method, setMethod] = useState(refund.method ?? "cash");
  const [reference, setReference] = useState(refund.reference ?? "");
  const [date, setDate] = useState(() => {
    const value = new Date(refund.refunded_at ?? refund.created_at);
    value.setMinutes(value.getMinutes() - value.getTimezoneOffset());
    return value.toISOString().slice(0, 16);
  });
  const mutation = useMutation({
    mutationFn: () => amendRefund(makerspaceId, paymentId, refund.id, {
      method, reference, refunded_at: new Date(date).toISOString(),
    }),
    onSuccess: () => { invalidatePaymentViews(client, makerspaceId); onClose(); },
  });
  return <Modal open onClose={onClose} title="Correct refund receipt" footer={<>
    <button className="desk-button" onClick={onClose} disabled={mutation.isPending}>Cancel</button>
    <button className="desk-button-primary" type="submit" form="amend-refund-form" disabled={mutation.isPending}>Save correction</button>
  </>}>
    <p className="text-sm text-muted">The amount stays the same. This appends a receipt correction and does not return money again.</p>
    <form id="amend-refund-form" className="mt-3 grid gap-3" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
      <Field label="Refund method"><select className="desk-input" value={method} onChange={(event) => setMethod(event.target.value)}>
        {SETTLEMENT_METHODS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select></Field>
      <Field label="Refund reference"><input className="desk-input" maxLength={64} value={reference} onChange={(event) => setReference(event.target.value)} /></Field>
      <Field label="Returned at"><input className="desk-input" type="datetime-local" required value={date} onChange={(event) => setDate(event.target.value)} /></Field>
      {mutation.error ? <p role="alert" className="text-danger">{mutation.error.message}</p> : null}
    </form>
  </Modal>;
}
