import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Field } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { type Makerspace, useStaffGet } from "./StaffPanels";

type ApiSettings = {
  smtp_host: string;
  smtp_port: number;
  smtp_username: string;
  smtp_password_set: boolean;
  smtp_use_tls: boolean;
  smtp_use_ssl: boolean;
  smtp_from_email: string;
};

type SmtpSettingsForm = {
  smtp_host: string;
  smtp_port: string;
  smtp_username: string;
  smtp_password: string;
  smtp_use_tls: boolean;
  smtp_use_ssl: boolean;
  smtp_from_email: string;
};

type NotificationRecipient = {
  id: number;
  username: string;
  email: string;
  role: "space_manager" | "inventory_manager" | "machine_manager";
  receives_notifications: boolean;
};

export function MakerspaceEmailSettings({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const [smtpForm, setSmtpForm] = useState<SmtpSettingsForm>({
    smtp_host: "",
    smtp_port: "587",
    smtp_username: "",
    smtp_password: "",
    smtp_use_tls: true,
    smtp_use_ssl: false,
    smtp_from_email: "",
  });
  const [recipientChecks, setRecipientChecks] = useState<Record<number, boolean>>({});
  const [recipientsDirty, setRecipientsDirty] = useState(false);

  const settings = useStaffGet<ApiSettings>(
    ["api-settings", makerspace.id],
    `/admin/makerspace/${makerspace.id}/api-settings`,
  );
  const recipients = useStaffGet<NotificationRecipient[]>(
    ["notification-recipients", makerspace.id],
    `/admin/makerspace/${makerspace.id}/notification-recipients`,
  );

  useEffect(() => {
    if (!settings.data) return;
    setSmtpForm({
      smtp_host: settings.data.smtp_host ?? "",
      smtp_port: String(settings.data.smtp_port ?? 587),
      smtp_username: settings.data.smtp_username ?? "",
      smtp_password: "",
      smtp_use_tls: settings.data.smtp_use_tls,
      smtp_use_ssl: settings.data.smtp_use_ssl,
      smtp_from_email: settings.data.smtp_from_email ?? "",
    });
  }, [settings.data]);

  useEffect(() => {
    if (!recipients.data) return;
    setRecipientChecks(
      Object.fromEntries(
        recipients.data.map((recipient) => [recipient.id, recipient.receives_notifications]),
      ),
    );
    setRecipientsDirty(false);
  }, [recipients.data]);

  const saveSmtpSettings = useMutation({
    mutationFn: () =>
      staffRequest<ApiSettings>(`/admin/makerspace/${makerspace.id}/api-settings`, {
        method: "PATCH",
        body: JSON.stringify(smtpPayload(smtpForm)),
      }),
    onSuccess: () => {
      setSmtpForm((current) => ({ ...current, smtp_password: "" }));
      queryClient.invalidateQueries({ queryKey: ["api-settings", makerspace.id] });
    },
  });

  const clearSmtpPassword = useMutation({
    mutationFn: () =>
      staffRequest<ApiSettings>(`/admin/makerspace/${makerspace.id}/api-settings`, {
        method: "PATCH",
        body: JSON.stringify({ smtp_password: "" }),
      }),
    onSuccess: () => {
      setSmtpForm((current) => ({ ...current, smtp_password: "" }));
      queryClient.invalidateQueries({ queryKey: ["api-settings", makerspace.id] });
    },
  });
  const saveRecipients = useMutation({
    mutationFn: () =>
      staffRequest<NotificationRecipient[]>(
        `/admin/makerspace/${makerspace.id}/notification-recipients`,
        {
          method: "PATCH",
          body: JSON.stringify({
            recipients: (recipients.data ?? []).map((recipient) => ({
              id: recipient.id,
              receives_notifications:
                recipientChecks[recipient.id] ?? recipient.receives_notifications,
            })),
          }),
        },
      ),
    onSuccess: (updated) => {
      setRecipientChecks(
        Object.fromEntries(
          updated.map((recipient) => [recipient.id, recipient.receives_notifications]),
        ),
      );
      setRecipientsDirty(false);
      queryClient.invalidateQueries({ queryKey: ["notification-recipients", makerspace.id] });
    },
  });

  return (
    <>
      <div className="rounded-md border border-line bg-bg p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid max-w-2xl gap-2">
            <h3 className="text-base font-semibold text-ink">Email (SMTP)</h3>
            <p className="text-sm text-muted">
              Configure the sender used for staff lifecycle notifications.
            </p>
          </div>
          <div className="desk-actions flex flex-wrap gap-2">
            <button
              className="desk-button-primary"
              type="button"
              disabled={!settings.isSuccess || saveSmtpSettings.isPending}
              onClick={() => saveSmtpSettings.mutate()}
            >
              {saveSmtpSettings.isPending ? "Saving..." : "Save email settings"}
            </button>
            <button
              className="desk-button"
              type="button"
              disabled={!settings.data?.smtp_password_set || clearSmtpPassword.isPending}
              onClick={() => clearSmtpPassword.mutate()}
            >
              {clearSmtpPassword.isPending ? "Clearing..." : "Clear SMTP password"}
            </button>
          </div>
        </div>
        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          <Field label="SMTP host"><input className="desk-input" value={smtpForm.smtp_host} onChange={(event) => setSmtpForm({ ...smtpForm, smtp_host: event.target.value })} /></Field>
          <Field label="SMTP port"><input className="desk-input" inputMode="numeric" value={smtpForm.smtp_port} onChange={(event) => setSmtpForm({ ...smtpForm, smtp_port: event.target.value })} /></Field>
          <Field label="SMTP username"><input className="desk-input" value={smtpForm.smtp_username} onChange={(event) => setSmtpForm({ ...smtpForm, smtp_username: event.target.value })} /></Field>
          <Field label="SMTP password"><input className="desk-input" placeholder={settings.data?.smtp_password_set ? "SMTP password set" : undefined} type="password" value={smtpForm.smtp_password} onChange={(event) => setSmtpForm({ ...smtpForm, smtp_password: event.target.value })} /></Field>
          <Field className="sm:col-span-2" label="SMTP from email"><input className="desk-input sm:col-span-2" value={smtpForm.smtp_from_email} onChange={(event) => setSmtpForm({ ...smtpForm, smtp_from_email: event.target.value })} /></Field>
        </div>
        <div className="mt-3 flex flex-wrap gap-4">
          <label className="flex items-center gap-2 text-sm text-muted">
            <input
              type="checkbox"
              checked={smtpForm.smtp_use_tls}
              onChange={(event) =>
                setSmtpForm({ ...smtpForm, smtp_use_tls: event.target.checked, smtp_use_ssl: event.target.checked ? false : smtpForm.smtp_use_ssl })
              }
            />
            Use STARTTLS (587)
          </label>
          <label className="flex items-center gap-2 text-sm text-muted">
            <input
              type="checkbox"
              checked={smtpForm.smtp_use_ssl}
              onChange={(event) =>
                setSmtpForm({ ...smtpForm, smtp_use_ssl: event.target.checked, smtp_use_tls: event.target.checked ? false : smtpForm.smtp_use_tls })
              }
            />
            Use implicit SSL (465)
          </label>
        </div>
        {settings.isLoading ? <p className="mt-2 text-sm text-muted">Loading email settings...</p> : null}
        {settings.error ? <p className="mt-2 text-sm text-danger">{settings.error.message}</p> : null}
        {saveSmtpSettings.error ? (
          <p className="mt-2 text-sm text-danger">{saveSmtpSettings.error.message}</p>
        ) : null}
        {clearSmtpPassword.error ? (
          <p className="mt-2 text-sm text-danger">{clearSmtpPassword.error.message}</p>
        ) : null}
      </div>

      <div className="rounded-md border border-line bg-bg p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid max-w-2xl gap-2">
            <h3 className="text-base font-semibold text-ink">Notification recipients</h3>
            <p className="text-sm text-muted">
              Unchecked managers will not receive hardware/printing lifecycle emails for this
              makerspace.
            </p>
          </div>
          <button
            className="desk-button-primary"
            type="button"
            disabled={!recipients.isSuccess || !recipientsDirty || saveRecipients.isPending || !recipients.data?.length}
            onClick={() => saveRecipients.mutate()}
          >
            {saveRecipients.isPending ? "Saving..." : "Save recipients"}
          </button>
        </div>
        {recipients.isLoading ? <p className="mt-3 text-sm text-muted">Loading recipients...</p> : null}
        <div className="mt-4 grid gap-2">
          {recipients.data?.map((recipient) => (
            <label
              key={recipient.id}
              className="flex items-start gap-3 rounded-md border border-line bg-surface p-3 text-sm text-ink"
            >
              <input
                className="mt-1 h-4 w-4"
                type="checkbox"
                checked={recipientChecks[recipient.id] ?? recipient.receives_notifications}
                onChange={(event) => {
                  setRecipientChecks({
                    ...recipientChecks,
                    [recipient.id]: event.target.checked,
                  });
                  setRecipientsDirty(true);
                }}
              />
              <span>
                <span className="font-semibold">{recipient.username}</span>
                <span className="block text-muted">
                  {recipient.email} - {roleLabel(recipient.role)}
                </span>
              </span>
            </label>
          ))}
        </div>
        {!recipients.isLoading && recipients.data?.length === 0 ? (
          <p className="mt-3 text-sm text-muted">No managers to notify yet.</p>
        ) : null}
        {recipients.error ? <p className="mt-3 text-sm text-danger">{recipients.error.message}</p> : null}
        {saveRecipients.error ? (
          <p className="mt-3 text-sm text-danger">{saveRecipients.error.message}</p>
        ) : null}
      </div>
    </>
  );
}

function smtpPayload(form: SmtpSettingsForm) {
  const payload: Record<string, string | number | boolean> = {
    smtp_host: form.smtp_host,
    smtp_port: Number(form.smtp_port) || 587,
    smtp_username: form.smtp_username,
    smtp_use_tls: form.smtp_use_tls,
    smtp_use_ssl: form.smtp_use_ssl,
    smtp_from_email: form.smtp_from_email,
  };
  if (form.smtp_password) payload.smtp_password = form.smtp_password;
  return payload;
}

function roleLabel(role: NotificationRecipient["role"]) {
  return {
    space_manager: "Space manager",
    inventory_manager: "Inventory manager",
    machine_manager: "Machine manager",
  }[role];
}
