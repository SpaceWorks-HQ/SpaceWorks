import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import type { Makerspace } from "./StaffPanels";

type Props = {
  makerspace: Makerspace;
  settings?: Makerspace;
  loading: boolean;
};

export function MakerspacePublicStatsSettings({ makerspace, settings, loading }: Props) {
  const queryClient = useQueryClient();
  const publicStatsEnabled = settings?.public_stats_enabled ?? makerspace.public_stats_enabled ?? false;
  const showHolderNames =
    settings?.public_stats_show_holder_names ?? makerspace.public_stats_show_holder_names ?? false;

  const invalidateSettings = () => {
    queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
    queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
    queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
  };
  const updatePublicStats = useMutation({
    mutationFn: (next: boolean) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ public_stats_enabled: next }),
      }),
    onSuccess: invalidateSettings,
  });
  const updateHolderNames = useMutation({
    mutationFn: (next: boolean) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ public_stats_show_holder_names: next }),
      }),
    onSuccess: invalidateSettings,
  });

  return (
    <div className="grid min-w-0 gap-4 rounded-md border border-line bg-bg p-4">
      <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
        <div className="grid min-w-0 max-w-2xl gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-ink">Public stats page</h3>
            <Badge tone={publicStatsEnabled ? "success" : "neutral"}>
              {publicStatsEnabled ? "On" : "Off"}
            </Badge>
          </div>
          <p className="text-sm text-muted">
            Publish a public activity page with print hours, popular hardware, and current loans at{" "}
            <code>/m/{makerspace.slug}/stats</code>. Borrower names are controlled separately below. When
            off, the page and its API return 404 and the link is hidden.
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
            disabled={loading || updatePublicStats.isPending}
            onChange={(event) => updatePublicStats.mutate(event.target.checked)}
          />
          <span className="font-semibold">Publish public stats</span>
        </label>
      </div>
      <div className="grid min-w-0 gap-3 border-t border-line pt-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
        <div className="grid min-w-0 max-w-2xl gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-ink">Public borrower names</h3>
            <Badge tone={showHolderNames ? "warn" : "neutral"}>{showHolderNames ? "On" : "Off"}</Badge>
          </div>
          <p className="text-sm text-muted">
            When on, each current loan publishes the borrower&apos;s name on the unauthenticated public
            stats page. When off, every borrower is shown as &quot;Member&quot;.
          </p>
          {updateHolderNames.error ? (
            <p className="text-sm text-danger">{updateHolderNames.error.message}</p>
          ) : null}
        </div>
        <label className="flex min-w-0 items-start gap-3 text-sm text-ink sm:justify-self-start md:justify-self-end">
          <input
            className="mt-1 h-4 w-4"
            type="checkbox"
            checked={showHolderNames}
            disabled={loading || updateHolderNames.isPending}
            onChange={(event) => updateHolderNames.mutate(event.target.checked)}
          />
          <span className="font-semibold">Publish borrower names publicly</span>
        </label>
      </div>
    </div>
  );
}
