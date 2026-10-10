import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { Panel, useStaffGet } from "./StaffPanels";

type SocialSettings = {
  google_web_client_id: string;
  google_ios_client_id: string;
  google_android_client_id: string;
  apple_service_id: string;
  apple_native_app_ids: string[];
  apple_team_id: string;
  apple_key_id: string;
  apple_private_key_set: boolean;
};

export function PlatformSocialAuthPanel() {
  const queryClient = useQueryClient();
  const settings = useStaffGet<SocialSettings>(["platform-social-auth"], "/admin/platform/social-auth-settings");
  const [form, setForm] = useState({
    google_web_client_id: "",
    google_ios_client_id: "",
    google_android_client_id: "",
    apple_service_id: "",
    apple_native_app_ids: "",
    apple_team_id: "",
    apple_key_id: "",
    apple_private_key: "",
  });

  useEffect(() => {
    if (!settings.data) return;
    setForm({
      google_web_client_id: settings.data.google_web_client_id,
      google_ios_client_id: settings.data.google_ios_client_id,
      google_android_client_id: settings.data.google_android_client_id,
      apple_service_id: settings.data.apple_service_id,
      apple_native_app_ids: settings.data.apple_native_app_ids.join("\n"),
      apple_team_id: settings.data.apple_team_id,
      apple_key_id: settings.data.apple_key_id,
      apple_private_key: "",
    });
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () => staffRequest<SocialSettings>("/admin/platform/social-auth-settings", {
      method: "PATCH",
      body: JSON.stringify({
        ...form,
        apple_native_app_ids: form.apple_native_app_ids.split(/[,\n]/).map((item) => item.trim()).filter(Boolean),
        ...(form.apple_private_key ? {} : { apple_private_key: undefined }),
      }),
    }),
    onSuccess: () => {
      setForm((current) => ({ ...current, apple_private_key: "" }));
      void queryClient.invalidateQueries({ queryKey: ["platform-social-auth"] });
    },
  });
  const disabled = settings.isLoading || save.isPending;

  return (
    <Panel title="Google and Apple sign-in">
      <p className="text-sm text-muted">
        Platform-wide identities link to global accounts; makerspace permissions still come from each membership.
      </p>
      {settings.data ? <div className="mt-2 text-sm text-muted">
        <p>Google: {[settings.data.google_web_client_id, settings.data.google_ios_client_id, settings.data.google_android_client_id].some((id) => id.trim()) ? "Client IDs configured" : "Not configured"}</p>
        <p>Apple: {settings.data.apple_service_id.trim() || settings.data.apple_native_app_ids.length ? "Audiences configured" : "Not configured"}</p>
      </div> : null}
      <div className="mt-4 space-y-5">
        <fieldset disabled={disabled} className="space-y-3">
          <legend className="font-semibold text-ink">Google OAuth clients</legend>
          <LabeledInput label="Web client ID" value={form.google_web_client_id} onChange={(value) => setForm({ ...form, google_web_client_id: value })} />
          <div className="grid gap-3 sm:grid-cols-2">
            <LabeledInput label="iOS client ID" value={form.google_ios_client_id} onChange={(value) => setForm({ ...form, google_ios_client_id: value })} />
            <LabeledInput label="Android client ID" value={form.google_android_client_id} onChange={(value) => setForm({ ...form, google_android_client_id: value })} />
          </div>
        </fieldset>
        <fieldset disabled={disabled} className="space-y-3 border-t border-line pt-5">
          <legend className="font-semibold text-ink">Apple Sign in</legend>
          <LabeledInput label="Web Service ID" value={form.apple_service_id} onChange={(value) => setForm({ ...form, apple_service_id: value })} />
          <label className="block text-sm font-semibold text-ink">Native app audiences
            <textarea className="desk-input mt-1 min-h-20 w-full" value={form.apple_native_app_ids} onChange={(event) => setForm({ ...form, apple_native_app_ids: event.target.value })} placeholder="One audience per line" />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <LabeledInput label="Team ID" value={form.apple_team_id} onChange={(value) => setForm({ ...form, apple_team_id: value })} />
            <LabeledInput label="Key ID" value={form.apple_key_id} onChange={(value) => setForm({ ...form, apple_key_id: value })} />
          </div>
          <label className="block text-sm font-semibold text-ink">Apple private key (.p8)
            <textarea className="desk-input mt-1 min-h-24 w-full font-mono text-xs" value={form.apple_private_key} onChange={(event) => setForm({ ...form, apple_private_key: event.target.value })} placeholder={settings.data?.apple_private_key_set ? "Private key set — leave blank to keep it" : "Paste the private key"} />
          </label>
        </fieldset>
        <button className="desk-button-primary w-full" disabled={disabled} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save social sign-in settings"}
        </button>
        {settings.error || save.error ? <p className="text-sm text-danger" role="alert">{(settings.error ?? save.error)?.message}</p> : null}
      </div>
    </Panel>
  );
}

function LabeledInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="block text-sm font-semibold text-ink">{label}<input className="desk-input mt-1 w-full" value={value} onChange={(event) => onChange(event.target.value)} /></label>;
}
