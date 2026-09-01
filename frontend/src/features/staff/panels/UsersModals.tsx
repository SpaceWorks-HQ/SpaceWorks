import { useEffect, useState } from "react";

import { Field, Modal } from "../../../components/ui";

export type StaffForm = {
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  password: string;
  role_id: number | "";
  makerspace_id: string;
};
export type RestrictForm = { status: "restricted" | "suspended"; reason: string };
export type MakerspaceForm = {
  name: string;
  public_code: string;
  slug: string;
  location: string;
  superadmin_access_enabled: boolean;
};
export type ResetPasswordForm = { password: string };
export type ResetPasswordResult = { username: string; temporary_password: string };

export function AddStaffModal({
  open,
  form,
  makerspaceName,
  pending,
  error,
  roles,
  onChange,
  onClose,
  onSubmit,
}: {
  open: boolean;
  form: StaffForm;
  makerspaceName: string;
  pending: boolean;
  error: unknown;
  roles: { id: number; name: string }[];
  onChange: (form: StaffForm) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const errors = validationErrors(error);
  // Password is required: the API does not return an auto-generated one, so a
  // blank password would create an account nobody can sign into.
  const disabled = pending || !form.username.trim() || !form.password || !form.role_id;
  return (
    <Modal open={open} onClose={onClose} title="Add staff" footer={<ModalActions pending={pending} disabled={disabled} onClose={onClose} onSubmit={onSubmit} />}>
      <form className="grid gap-3 text-sm" onSubmit={(event) => { event.preventDefault(); if (!disabled) onSubmit(); }}>
        <Field label="Username" error={errors.username}>
          <input className="desk-input w-full" value={form.username} onChange={(event) => onChange({ ...form, username: event.target.value })} />
        </Field>
        <Field label="Email" error={errors.email}>
          <input className="desk-input w-full" type="email" value={form.email} onChange={(event) => onChange({ ...form, email: event.target.value })} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="First name" error={errors.first_name}>
            <input className="desk-input w-full" value={form.first_name} onChange={(event) => onChange({ ...form, first_name: event.target.value })} />
          </Field>
          <Field label="Last name" error={errors.last_name}>
            <input className="desk-input w-full" value={form.last_name} onChange={(event) => onChange({ ...form, last_name: event.target.value })} />
          </Field>
        </div>
        <Field label="Password" hint="Required - share it with the new staff member." error={errors.password}>
          <input className="desk-input w-full" type="password" autoComplete="new-password" value={form.password} onChange={(event) => onChange({ ...form, password: event.target.value })} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Role" error={errors.role_id}>
            <select className="desk-input w-full" value={form.role_id} onChange={(event) => onChange({ ...form, role_id: Number(event.target.value) || "" })}>
              <option value="">Select role</option>
              {roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}
            </select>
          </Field>
          <Field label="Makerspace">
            <div className="desk-input flex w-full items-center bg-surface text-muted">{makerspaceName}</div>
          </Field>
        </div>
        <GeneralError error={error} errors={errors} />
      </form>
    </Modal>
  );
}

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

export function ResetPasswordModal({
  open,
  userLabel,
  form,
  pending,
  error,
  result,
  onChange,
  onClose,
  onSubmit,
}: {
  open: boolean;
  userLabel: string;
  form: ResetPasswordForm;
  pending: boolean;
  error: unknown;
  result: ResetPasswordResult | null;
  onChange: (form: ResetPasswordForm) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const errors = validationErrors(error);
  const hasShortPassword = form.password.length > 0 && form.password.length < 8;
  const disabled = pending || hasShortPassword;

  useEffect(() => {
    setCopied(false);
  }, [open, result?.temporary_password]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Reset password for ${userLabel}`}
      footer={
        result ? (
          <div className="desk-actions flex flex-wrap justify-end gap-2">
            <button className="desk-button-primary" type="button" onClick={onClose}>Close</button>
          </div>
        ) : (
          <ModalActions
            pending={pending}
            disabled={disabled}
            submitLabel="Reset password"
            onClose={onClose}
            onSubmit={onSubmit}
          />
        )
      }
    >
      {result ? (
        <div className="grid gap-3 text-sm">
          <p className="text-muted">Share this with the user securely. It won't be shown again.</p>
          <div className="rounded-md border border-accent/40 bg-accent/10 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <code className="break-all font-mono text-base font-semibold text-ink">
                {result.temporary_password}
              </code>
              <button
                className="desk-button-ghost"
                type="button"
                onClick={() => {
                  void navigator.clipboard.writeText(result.temporary_password).then(() => setCopied(true));
                }}
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
          </div>
        </div>
      ) : (
        <form className="grid gap-3 text-sm" onSubmit={(event) => { event.preventDefault(); if (!disabled) onSubmit(); }}>
          <p className="text-muted">
            A temporary password will be generated. The user must change it at next sign-in. You can run this again anytime.
          </p>
          <Field
            label="Temporary password"
            hint="Optional. Leave blank to auto-generate."
            error={errors.password ?? (hasShortPassword ? "Use at least 8 characters, or leave blank to auto-generate." : undefined)}
          >
            <input
              className="desk-input w-full"
              minLength={8}
              type="password"
              value={form.password}
              onChange={(event) => onChange({ ...form, password: event.target.value })}
            />
          </Field>
          <GeneralError error={error} errors={errors} />
        </form>
      )}
    </Modal>
  );
}

function ModalActions({
  pending,
  disabled,
  submitLabel = "Save",
  onClose,
  onSubmit,
}: {
  pending: boolean;
  disabled: boolean;
  submitLabel?: string;
  onClose: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="desk-actions flex flex-wrap justify-end gap-2">
      <button className="desk-button-ghost" type="button" disabled={pending} onClick={onClose}>Cancel</button>
      <button className="desk-button-primary" type="button" disabled={disabled} onClick={onSubmit}>{submitLabel}</button>
    </div>
  );
}

function GeneralError({ error, errors }: { error: unknown; errors: Record<string, string> }) {
  const message = error instanceof Error ? error.message : "";
  if (!message || Object.keys(errors).length) return null;
  return <p className="text-sm text-danger">{message}</p>;
}

function validationErrors(error: unknown) {
  if (!error || !(error instanceof Error)) return {};
  try {
    const parsed = JSON.parse(error.message) as Record<string, unknown>;
    return flattenErrors(parsed);
  } catch {
    return {};
  }
}

function flattenErrors(value: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      key,
      Array.isArray(item) ? item.join(" ") : typeof item === "string" ? item : JSON.stringify(item),
    ]),
  );
}
