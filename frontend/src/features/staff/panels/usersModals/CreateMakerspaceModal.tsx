import { Field, Modal } from "../../../../components/ui";

import { GeneralError, ModalActions, validationErrors } from "./shared";
import { type MakerspaceForm } from "./types";

export function CreateMakerspaceModal({
  open,
  form,
  pending,
  error,
  onChange,
  onClose,
  onSubmit,
}: {
  open: boolean;
  form: MakerspaceForm;
  pending: boolean;
  error: unknown;
  onChange: (form: MakerspaceForm) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const errors = validationErrors(error);
  const disabled = pending || !form.name.trim() || !form.public_code.trim() || !form.slug.trim();
  return (
    <Modal open={open} onClose={onClose} title="Create makerspace" footer={<ModalActions pending={pending} disabled={disabled} onClose={onClose} onSubmit={onSubmit} />}>
      <form className="grid gap-3 text-sm" onSubmit={(event) => { event.preventDefault(); if (!disabled) onSubmit(); }}>
        <Field label="Name" error={errors.name}>
          <input className="desk-input w-full" value={form.name} onChange={(event) => onChange({ ...form, name: event.target.value })} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Public code" error={errors.public_code}>
            <input className="desk-input w-full uppercase" maxLength={4} value={form.public_code} onChange={(event) => onChange({ ...form, public_code: event.target.value.toUpperCase() })} />
          </Field>
          <Field label="Slug" error={errors.slug}>
            <input className="desk-input w-full" value={form.slug} onChange={(event) => onChange({ ...form, slug: event.target.value })} />
          </Field>
        </div>
        <Field label="Location" error={errors.location}>
          <input className="desk-input w-full" value={form.location} onChange={(event) => onChange({ ...form, location: event.target.value })} />
        </Field>
        <label className="flex items-start gap-3 rounded-md border border-line bg-surface p-3 text-sm">
          <input
            className="mt-1 h-4 w-4 accent-accent"
            type="checkbox"
            checked={form.superadmin_access_enabled}
            onChange={(event) => onChange({ ...form, superadmin_access_enabled: event.target.checked })}
          />
          <span className="grid gap-1">
            <span className="font-semibold text-ink">Superadmin can access this makerspace</span>
            <span className="text-xs text-muted">
              Uncheck for a collaborating makerspace that should be hidden from your reports/admin views. Only their admin can re-enable it.
            </span>
            {errors.superadmin_access_enabled ? <span className="text-xs font-normal text-danger">{errors.superadmin_access_enabled}</span> : null}
          </span>
        </label>
        <GeneralError error={error} errors={errors} />
      </form>
    </Modal>
  );
}
