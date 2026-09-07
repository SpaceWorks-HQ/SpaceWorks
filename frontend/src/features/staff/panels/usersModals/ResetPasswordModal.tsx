import { useEffect, useState } from "react";

import { Field, Modal } from "../../../../components/ui";

import { GeneralError, ModalActions, validationErrors } from "./shared";
import { type ResetPasswordForm, type ResetPasswordResult } from "./types";

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
