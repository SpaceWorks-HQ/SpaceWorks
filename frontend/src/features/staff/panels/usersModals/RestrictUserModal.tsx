import { Field, Modal } from "../../../../components/ui";

import { GeneralError, ModalActions, validationErrors } from "./shared";
import { type RestrictForm } from "./types";

export function RestrictUserModal({
  open,
  userLabel,
  form,
  pending,
  error,
  onChange,
  onClose,
  onSubmit,
}: {
  open: boolean;
  userLabel: string;
  form: RestrictForm;
  pending: boolean;
  error: unknown;
  onChange: (form: RestrictForm) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const errors = validationErrors(error);
  const disabled = pending || !form.reason.trim();
  return (
    <Modal open={open} onClose={onClose} title={`Restrict ${userLabel}`} footer={<ModalActions pending={pending} disabled={disabled} submitLabel="Apply" onClose={onClose} onSubmit={onSubmit} />}>
      <form className="grid gap-3 text-sm" onSubmit={(event) => { event.preventDefault(); if (!disabled) onSubmit(); }}>
        <Field label="Status" error={errors.status}>
          <select className="desk-input w-full" value={form.status} onChange={(event) => onChange({ ...form, status: event.target.value as RestrictForm["status"] })}>
            <option value="restricted">Restricted</option>
            <option value="suspended">Suspended</option>
          </select>
        </Field>
        <Field label="Reason" error={errors.reason}>
          <textarea className="desk-input h-24 w-full" value={form.reason} onChange={(event) => onChange({ ...form, reason: event.target.value })} />
        </Field>
        <GeneralError error={error} errors={errors} />
      </form>
    </Modal>
  );
}
