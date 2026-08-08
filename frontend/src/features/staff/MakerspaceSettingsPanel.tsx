import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { MakerspaceBrandingSettings } from "./MakerspaceBrandingSettings";
import { MakerspaceBookingRulesSettings } from "./MakerspaceBookingRulesSettings";
import { MakerspaceBookingSettings } from "./MakerspaceBookingSettings";
import { MakerspaceCustomDomainSettings } from "./MakerspaceCustomDomainSettings";
import { MakerspaceEmailSettings } from "./MakerspaceEmailSettings";
import { MakerspaceFilamentSettings } from "./MakerspaceFilamentSettings";
import { MakerspaceFeatureSettings } from "./MakerspaceFeatureSettings";
import { MakerspaceGeofenceSettings } from "./MakerspaceGeofenceSettings";
import { MakerspaceGeneralSettings } from "./MakerspaceGeneralSettings";
import { IntegrationHealthPanel } from "./IntegrationHealthPanel";
import { MakerspaceLocationSettings } from "./MakerspaceLocationSettings";
import { MakerspaceMembershipSettings } from "./MakerspaceMembershipSettings";
import { MakerspacePaymentSettings } from "./MakerspacePaymentSettings";
import { MakerspaceSubdomainSettings } from "./MakerspaceSubdomainSettings";
import { MakerspaceWebhookSettings } from "./MakerspaceWebhookSettings";
import { NotificationDestinations } from "./NotificationDestinations";
import { NotificationMuteMatrix } from "./NotificationMuteMatrix";
import { NotificationRecipientPicker } from "./NotificationRecipientPicker";
import { Panel, type Makerspace, useStaffGet } from "./StaffPanels";

type Props = {
  makerspace: Makerspace;
  isSuperadmin: boolean;
};

export function MakerspaceSettingsPanel({ makerspace, isSuperadmin }: Props) {
  const queryClient = useQueryClient();
  const settings = useStaffGet<Makerspace>(
    ["makerspace-settings", makerspace.id],
    `/admin/makerspaces/${makerspace.id}`,
  );
  const superadminAccessEnabled =
    settings.data?.superadmin_access_enabled ?? makerspace.superadmin_access_enabled ?? true;
  const staffNotificationsEnabled =
    settings.data?.staff_notifications_enabled ?? makerspace.staff_notifications_enabled ?? true;
  const publicStatsEnabled =
    settings.data?.public_stats_enabled ?? makerspace.public_stats_enabled ?? false;
  const publicPrintStatusLookupPolicy =
    settings.data?.public_print_status_lookup_policy ?? makerspace.public_print_status_lookup_policy ?? "email_unverified";
  const enabledModules = settings.data?.enabled_modules ?? makerspace.enabled_modules ?? [];
  const reEnableBlocked = isSuperadmin && !superadminAccessEnabled;

  const updateAccess = useMutation({
    mutationFn: (next: boolean) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ superadmin_access_enabled: next }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
      queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
    },
  });

  const updateStaffNotifications = useMutation({
    mutationFn: (next: boolean) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ staff_notifications_enabled: next }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
      queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
    },
  });

  const updatePublicStats = useMutation({
    mutationFn: (next: boolean) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ public_stats_enabled: next }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
      queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
    },
  });
  const updatePrintStatusLookupPolicy = useMutation({
    mutationFn: (next: Makerspace["public_print_status_lookup_policy"]) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ public_print_status_lookup_policy: next }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
      queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
    },
  });



  const nextValue = !superadminAccessEnabled;
  const disabled = settings.isLoading || updateAccess.isPending || reEnableBlocked;
  const notificationsDisabled = settings.isLoading || updateStaffNotifications.isPending;
  return (
    <Panel title="Makerspace settings">
      <div className="grid min-w-0 gap-4">
        <MakerspaceBrandingSettings
          makerspace={makerspace}
          settings={settings.data}
          loading={settings.isLoading}
        />
        <MakerspaceGeneralSettings
          makerspace={makerspace}
          settings={settings.data}
          loading={settings.isLoading}
        />
        <MakerspaceLocationSettings
          makerspace={makerspace}
          settings={settings.data}
          loading={settings.isLoading}
        />
        <MakerspaceMembershipSettings makerspace={makerspace} settings={settings.data} loading={settings.isLoading} />
        <MakerspaceFeatureSettings
          makerspace={makerspace}
          settings={settings.data}
          loading={settings.isLoading}
        />
        <MakerspacePaymentSettings makerspace={settings.data ?? makerspace} />
        <MakerspaceGeofenceSettings makerspace={makerspace} settings={settings.data} loading={settings.isLoading} />
        <IntegrationHealthPanel makerspace={makerspace} />
        <div className="min-w-0 rounded-md border border-line bg-bg p-4">
          <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
            <div className="grid min-w-0 max-w-2xl gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-base font-semibold text-ink">Superadmin access</h3>
                <Badge tone={superadminAccessEnabled ? "success" : "warn"}>
                  {superadminAccessEnabled ? "On" : "Off"}
                </Badge>
              </div>
              <p className="text-sm text-muted">
                When off, this makerspace is hidden from the superadmin's reports, dashboards, audit,
                and admin lists. It does not revoke the superadmin's platform/database access. Only
                the makerspace admin can turn it back on.
              </p>
              {reEnableBlocked ? (
                <p className="text-sm text-muted">Re-enable is controlled by the makerspace admin.</p>
              ) : null}
              {updateAccess.error ? <p className="text-sm text-danger">{updateAccess.error.message}</p> : null}
            </div>
            <button
              className={`${superadminAccessEnabled ? "desk-button" : "desk-button-primary"} w-full max-w-full justify-self-start sm:w-auto md:justify-self-end`}
              type="button"
              disabled={disabled}
              onClick={() => updateAccess.mutate(nextValue)}
            >
              {updateAccess.isPending
                ? "Saving..."
                : superadminAccessEnabled
                  ? "Turn off access"
                  : "Turn on access"}
            </button>
          </div>
        </div>
        <div className="min-w-0 rounded-md border border-line bg-bg p-4">
          <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
            <div className="grid min-w-0 max-w-2xl gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-base font-semibold text-ink">Staff email notifications</h3>
                <Badge tone={staffNotificationsEnabled ? "success" : "neutral"}>
                  {staffNotificationsEnabled ? "On" : "Off"}
                </Badge>
              </div>
              <p className="text-sm text-muted">
                Email this makerspace&apos;s managers when hardware and print request statuses change.
              </p>
              {updateStaffNotifications.error ? (
                <p className="text-sm text-danger">{updateStaffNotifications.error.message}</p>
              ) : null}
            </div>
            <label className="flex min-w-0 items-start gap-3 text-sm text-ink sm:justify-self-start md:justify-self-end">
              <input
                className="mt-1 h-4 w-4"
                type="checkbox"
                checked={staffNotificationsEnabled}
                disabled={notificationsDisabled}
                onChange={(event) => updateStaffNotifications.mutate(event.target.checked)}
              />
              <span className="font-semibold">Send staff emails</span>
            </label>
          </div>
        </div>
        <div className="min-w-0 rounded-md border border-line bg-bg p-4">
          <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
            <div className="grid min-w-0 max-w-2xl gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-base font-semibold text-ink">Public stats page</h3>
                <Badge tone={publicStatsEnabled ? "success" : "neutral"}>
                  {publicStatsEnabled ? "On" : "Off"}
                </Badge>
              </div>
              <p className="text-sm text-muted">
                Publish a public activity page (print hours, popular hardware, who currently has tools
                out by name) at <code>/m/{makerspace.slug}/stats</code>. When off, the page and its API
                return 404 and the link is hidden.
              </p>
              {updatePublicStats.error ? (
                <p className="text-sm text-danger">{updatePublicStats.error.message}</p>
              ) : null}
            </div>
            <label className="flex min-w-0 items-start gap-3 text-sm text-ink sm:justify-self-start md:justify-self-end">
              <input
                className="mt-1 h-4 w-4"
                type="checkbox"
                checked={publicStatsEnabled}
                disabled={updatePublicStats.isPending}
                onChange={(event) => updatePublicStats.mutate(event.target.checked)}
              />
              <span className="font-semibold">Publish public stats</span>
            </label>
          </div>
        </div>
        <div className="min-w-0 rounded-md border border-line bg-bg p-4">
          <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,1fr)_minmax(220px,280px)] md:items-start">
            <div className="grid min-w-0 max-w-2xl gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-base font-semibold text-ink">Public print status recovery</h3>
                <Badge tone={publicPrintStatusLookupPolicy === "token_only" ? "neutral" : "success"}>
                  {statusLookupLabel(publicPrintStatusLookupPolicy)}
                </Badge>
              </div>
              <p className="text-sm text-muted">
                Controls whether public print requests can be recovered from an email address when the status link is lost.
              </p>
              {updatePrintStatusLookupPolicy.error ? (
                <p className="text-sm text-danger">{updatePrintStatusLookupPolicy.error.message}</p>
              ) : null}
            </div>
            <select
              className="desk-input w-full"
              value={publicPrintStatusLookupPolicy}
              disabled={settings.isLoading || updatePrintStatusLookupPolicy.isPending}
              onChange={(event) => updatePrintStatusLookupPolicy.mutate(event.target.value as Makerspace["public_print_status_lookup_policy"])}
            >
              <option value="token_only">Token only</option>
              <option value="email_unverified">Email lookup</option>
            </select>
          </div>
        </div>
        <MakerspaceBookingSettings makerspace={makerspace} settings={settings.data} loading={settings.isLoading} />
        {enabledModules.includes("bookings") ? (
          <MakerspaceBookingRulesSettings makerspace={makerspace} />
        ) : null}
        <MakerspaceFilamentSettings makerspace={makerspace} settings={settings.data} loading={settings.isLoading} />
        <MakerspaceEmailSettings makerspace={makerspace} />
        <MakerspaceWebhookSettings makerspace={makerspace} />
        {settings.data?.platform_hosting === true ? (
          <MakerspaceSubdomainSettings makerspace={makerspace} settings={settings.data} />
        ) : null}
        <MakerspaceCustomDomainSettings
          makerspace={makerspace}
          settings={settings.data}
          loading={settings.isLoading}
        />
        <div className="min-w-0 rounded-md border border-line bg-bg p-4">
          <h3 className="text-base font-semibold text-ink">Notification channels</h3>
          <NotificationMuteMatrix makerspaceId={makerspace.id} />
          <NotificationRecipientPicker makerspaceId={makerspace.id} />
          <NotificationDestinations
            availableChannels={enabledModules}
            makerspaceId={makerspace.id}
          />
        </div>
      </div>
    </Panel>
  );
}

function statusLookupLabel(policy: Makerspace["public_print_status_lookup_policy"]) {
  return {
    token_only: "Token only",
    email_unverified: "Email lookup",
  }[policy ?? "email_unverified"];
}
