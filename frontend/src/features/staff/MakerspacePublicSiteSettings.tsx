import { useMutation, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../lib/api";
import type { Makerspace } from "./panels/shared";

export function MakerspacePublicSiteSettings({ makerspace, loading }: { makerspace: Makerspace; loading: boolean }) {
  const client = useQueryClient();
  const update = useMutation({
    mutationFn: (patch: Pick<Makerspace, "public_site_enabled" | "public_landing_page">) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, { method: "PATCH", body: JSON.stringify(patch) }),
    onSuccess: () => {
      for (const key of ["makerspace-settings", "makerspaces", "tenant-bootstrap", "runtime-tenant", "runtime-tenant-origin", "public-makerspaces", "member"])
        void client.invalidateQueries({ queryKey: [key] });
      void client.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
    },
  });
  return <div className="mt-5 space-y-3">
    <label className="flex gap-3 text-sm font-semibold"><input type="checkbox"
      checked={makerspace.public_site_enabled ?? true} disabled={loading || update.isPending}
      onChange={(event) => update.mutate({ public_site_enabled: event.target.checked })} />Publish public site</label>
    <p className="text-xs text-muted">Controls directory visibility, browser embed keys and public machine pages. The inventory catalogue has its own switch.</p>
    <label className="grid gap-2 text-sm font-semibold">Public home
      <select className="desk-input" value={makerspace.public_landing_page ?? "auto"} disabled={loading || update.isPending}
        onChange={(event) => update.mutate({ public_landing_page: event.target.value as Makerspace["public_landing_page"] })}>
        {[["auto", "Automatic"], ["inventory", "Inventory"], ["events", "Events"], ["bookings", "Bookings"], ["machines", "Machines"], ["membership", "Membership"]].map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </label>
    <p className="text-xs text-muted">If the selected family is disabled, the home uses an available family.</p>
    {update.error ? <p role="alert" className="text-sm text-danger">{update.error.message}</p> : null}
  </div>;
}
