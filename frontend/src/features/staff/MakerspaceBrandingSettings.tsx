import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { ImageUploader } from "./ImageUploader";
import { MakerspaceThemeSettings } from "./MakerspaceThemeSettings";
import type { Makerspace } from "./StaffPanels";

type Props = {
  makerspace: Makerspace;
  settings?: Makerspace;
  loading: boolean;
};

export function MakerspaceBrandingSettings({ makerspace, settings, loading }: Props) {
  const queryClient = useQueryClient();
  const currentRegisteredName = settings?.name ?? makerspace.name;
  const [registeredNameInput, setRegisteredNameInput] = useState(currentRegisteredName);
  const [displayNameInput, setDisplayNameInput] = useState("");
  const currentDisplayName = settings?.branding_config?.display_name ?? "";

  useEffect(() => {
    setRegisteredNameInput(currentRegisteredName);
  }, [currentRegisteredName, makerspace.id]);

  useEffect(() => {
    setDisplayNameInput(currentDisplayName);
  }, [currentDisplayName, makerspace.id]);

  const refreshBranding = () => {
    queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
    queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
    queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
  };

  const updateRegisteredName = useMutation({
    mutationFn: (value: string) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: value }),
      }),
    onSuccess: refreshBranding,
  });

  const updateDisplayName = useMutation({
    mutationFn: (value: string) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ public_display_name: value }),
      }),
    onSuccess: refreshBranding,
  });

  const trimmedRegisteredName = registeredNameInput.trim();
  const registeredNameChanged = trimmedRegisteredName !== currentRegisteredName.trim();
  const registeredNameSaveDisabled =
    loading || updateRegisteredName.isPending || !trimmedRegisteredName || !registeredNameChanged;
  const trimmedDisplayName = displayNameInput.trim();
  const displayNameChanged = trimmedDisplayName !== currentDisplayName.trim();
  const displayNameSaveDisabled = loading || updateDisplayName.isPending || !displayNameChanged;

  return (
    <div className="min-w-0 rounded-md border border-line bg-bg p-4">
      <h3 className="text-base font-semibold text-ink">Branding</h3>
      <p className="mt-1 text-sm text-muted">
        Logo and cover image shown on this makerspace&apos;s public pages. When no logo is set,
        the makerspace name is shown as the wordmark.
      </p>
      <div className="mt-4 grid min-w-0 gap-4 lg:grid-cols-2">
        <ImageUploader
          endpoint={`/admin/makerspace/${makerspace.id}/logo`}
          currentUrl={settings?.logo_url}
          label="Logo"
          fit="contain"
          onChanged={refreshBranding}
        />
        <ImageUploader
          endpoint={`/admin/makerspace/${makerspace.id}/cover`}
          currentUrl={settings?.cover_image_url}
          label="Cover image (wide banner)"
          shape="wide"
          onChanged={refreshBranding}
        />
      </div>
      <div className="mt-4 grid min-w-0 gap-4 lg:grid-cols-2">
        <form
          className="grid min-w-0 gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!registeredNameSaveDisabled) {
              updateRegisteredName.mutate(trimmedRegisteredName);
            }
          }}
        >
          <label className="text-sm font-semibold text-ink" htmlFor="registered-name">
            Registered name
          </label>
          <input
            id="registered-name"
            className="desk-input"
            value={registeredNameInput}
            disabled={loading}
            onChange={(event) => setRegisteredNameInput(event.target.value)}
          />
          <p className="text-xs text-muted">
            The official name of this makerspace. Used across the app and as the public wordmark
            when no logo or public display name is set.
          </p>
          <div>
            <button
              className="desk-button-primary w-full max-w-full sm:w-auto"
              type="submit"
              disabled={registeredNameSaveDisabled}
            >
              {updateRegisteredName.isPending ? "Saving..." : "Save registered name"}
            </button>
          </div>
          {updateRegisteredName.error ? (
            <p className="text-sm text-danger">{updateRegisteredName.error.message}</p>
          ) : null}
        </form>
        <form
          className="grid min-w-0 gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!displayNameSaveDisabled) {
              updateDisplayName.mutate(trimmedDisplayName);
            }
          }}
        >
        <label className="text-sm font-semibold text-ink" htmlFor="public-display-name">
          Public display name
        </label>
        <input
          id="public-display-name"
          className="desk-input"
          placeholder={makerspace.name}
          value={displayNameInput}
          disabled={loading}
          onChange={(event) => setDisplayNameInput(event.target.value)}
        />
        <p className="text-xs text-muted">
          Shown on this makerspace&apos;s public pages. Leave blank to use the registered name (
          <span className="font-semibold text-ink">{makerspace.name}</span>).
        </p>
        <div>
          <button
            className="desk-button-primary w-full max-w-full sm:w-auto"
            type="submit"
            disabled={displayNameSaveDisabled}
          >
            {updateDisplayName.isPending ? "Saving..." : "Save display name"}
          </button>
        </div>
        {updateDisplayName.error ? (
          <p className="text-sm text-danger">{updateDisplayName.error.message}</p>
        ) : null}
        </form>
      </div>
      <MakerspaceThemeSettings makerspace={makerspace} settings={settings} loading={loading} />
    </div>
  );
}
