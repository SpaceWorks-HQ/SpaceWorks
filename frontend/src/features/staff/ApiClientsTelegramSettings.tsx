import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Field } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { type Makerspace, useStaffGet } from "./StaffPanels";

type ApiSettings = {
  telegram_group_chat_id: string;
  telegram_bot_token_set: boolean;
};

type TelegramSettingsForm = {
  telegram_group_chat_id: string;
  telegram_bot_token: string;
};

export function ApiClientsTelegramSettings({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const [settingsForm, setSettingsForm] = useState<TelegramSettingsForm>({
    telegram_group_chat_id: "",
    telegram_bot_token: "",
  });

  const settings = useStaffGet<ApiSettings>(
    ["api-settings", makerspace.id],
    `/admin/makerspace/${makerspace.id}/api-settings`,
  );

  useEffect(() => {
    if (!settings.data) return;
    setSettingsForm({
      telegram_group_chat_id: settings.data.telegram_group_chat_id ?? "",
      telegram_bot_token: "",
    });
  }, [settings.data]);

  const saveSettings = useMutation({
    mutationFn: () =>
      staffRequest<ApiSettings>(`/admin/makerspace/${makerspace.id}/api-settings`, {
        method: "PATCH",
        body: JSON.stringify(settingsPayload(settingsForm)),
      }),
    onSuccess: () => {
      setSettingsForm((current) => ({
        ...current,
        telegram_bot_token: "",
      }));
      queryClient.invalidateQueries({ queryKey: ["api-settings", makerspace.id] });
    },
  });

  const clearTelegramToken = useMutation({
    mutationFn: () =>
      staffRequest<ApiSettings>(`/admin/makerspace/${makerspace.id}/api-settings`, {
        method: "PATCH",
        body: JSON.stringify({ telegram_bot_token: "" }),
      }),
    onSuccess: () => {
      setSettingsForm((current) => ({ ...current, telegram_bot_token: "" }));
      queryClient.invalidateQueries({ queryKey: ["api-settings", makerspace.id] });
    },
  });
  const testTelegram = useMutation({
    mutationFn: () =>
      staffRequest<{ delivered: boolean; detail?: string }>("/integrations/telegram/test-alert", {
        method: "POST",
        body: JSON.stringify({
          makerspace_id: makerspace.id,
          message: `Test alert from ${makerspace.name}`,
        }),
      }),
  });

  return (
    <div className="rounded-md border border-line bg-surface p-3">
      <h3 className="font-semibold text-ink">Integration settings</h3>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <Field label="Telegram group chat ID">
          <input
            className="desk-input"
            value={settingsForm.telegram_group_chat_id}
            onChange={(event) =>
              setSettingsForm({ ...settingsForm, telegram_group_chat_id: event.target.value })
            }
          />
        </Field>
        <Field label="Telegram bot token">
          <input
            className="desk-input"
            placeholder={settings.data?.telegram_bot_token_set ? "Telegram bot token set" : undefined}
            type="password"
            value={settingsForm.telegram_bot_token}
            onChange={(event) =>
              setSettingsForm({ ...settingsForm, telegram_bot_token: event.target.value })
            }
          />
        </Field>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <button
          className="desk-button-primary w-full"
          disabled={!settings.isSuccess || saveSettings.isPending}
          onClick={() => saveSettings.mutate()}
        >
          {saveSettings.isPending ? "Saving..." : "Save integration settings"}
        </button>
        <button
          className="desk-button w-full"
          type="button"
          disabled={!settings.data?.telegram_bot_token_set || clearTelegramToken.isPending}
          onClick={() => clearTelegramToken.mutate()}
        >
          {clearTelegramToken.isPending ? "Clearing..." : "Clear Telegram token"}
        </button>
      </div>
      <button
        className="desk-button mt-2 w-full"
        disabled={!settings.isSuccess || testTelegram.isPending}
        onClick={() => testTelegram.mutate()}
      >
        {testTelegram.isPending ? "Sending..." : "Send Telegram test alert"}
      </button>
      {settings.isLoading ? <p className="mt-2 text-sm text-muted">Loading integration settings...</p> : null}
      {settings.error ? <p className="mt-2 text-sm text-danger">{settings.error.message}</p> : null}
      {saveSettings.error ? <p className="mt-2 text-sm text-danger">{saveSettings.error.message}</p> : null}
      {clearTelegramToken.error ? <p className="mt-2 text-sm text-danger">{clearTelegramToken.error.message}</p> : null}
      {testTelegram.data ? (
        <p className={`mt-2 text-sm ${testTelegram.data.delivered ? "text-muted" : "text-danger"}`}>
          Telegram delivered: {testTelegram.data.delivered ? "yes" : "no"}
          {!testTelegram.data.delivered && testTelegram.data.detail ? ` - ${testTelegram.data.detail}` : ""}
        </p>
      ) : null}
      {testTelegram.error ? <p className="mt-2 text-sm text-danger">{testTelegram.error.message}</p> : null}
    </div>
  );
}

function settingsPayload(form: TelegramSettingsForm) {
  const payload: Record<string, string> = {
    telegram_group_chat_id: form.telegram_group_chat_id,
  };
  if (form.telegram_bot_token) payload.telegram_bot_token = form.telegram_bot_token;
  return payload;
}
