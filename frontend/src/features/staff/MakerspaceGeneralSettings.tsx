import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { MakerspaceLoanPolicySettings } from "./MakerspaceLoanPolicySettings";
import type { Makerspace } from "./panels/shared";

type Props = {
  makerspace: Makerspace;
  settings?: Makerspace;
  loading: boolean;
};

export function MakerspaceGeneralSettings({ makerspace, settings, loading }: Props) {
  const queryClient = useQueryClient();
  const currentDefaultLoanDays = settings?.default_loan_days ?? makerspace.default_loan_days ?? 7;
  const publicInventoryEnabled =
    settings?.public_inventory_enabled ?? makerspace.public_inventory_enabled ?? true;
  const [defaultLoanDays, setDefaultLoanDays] = useState(String(currentDefaultLoanDays));

  useEffect(() => {
    setDefaultLoanDays(String(currentDefaultLoanDays));
  }, [currentDefaultLoanDays, makerspace.id]);

  const refreshSettings = () => {
    queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
    queryClient.invalidateQueries({ queryKey: ["staff", "loan-policy", makerspace.id] });
    queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
    queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
  };

  const updateDefaultLoanDays = useMutation({
    mutationFn: (value: string) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ default_loan_days: Number(value) || 7 }),
      }),
    onSuccess: refreshSettings,
  });

  const updatePublicInventory = useMutation({
    mutationFn: (next: boolean) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ public_inventory_enabled: next }),
      }),
    onSuccess: refreshSettings,
  });

  return (
    <div className="min-w-0 rounded-md border border-line bg-bg p-4">
      <h3 className="text-base font-semibold text-ink">General</h3>
      <div className="mt-4 grid min-w-0 gap-5 lg:grid-cols-2">
        <form
          className="grid min-w-0 gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            updateDefaultLoanDays.mutate(defaultLoanDays);
          }}
        >
          <label className="text-sm font-semibold text-ink" htmlFor="default-loan-days">
            Default loan days
          </label>
          <input
            id="default-loan-days"
            className="desk-input"
            type="number"
            min="1"
            value={defaultLoanDays}
            disabled={loading || updateDefaultLoanDays.isPending}
            onChange={(event) => setDefaultLoanDays(event.target.value)}
          />
          <p className="text-xs text-muted">
            Default return window applied when a hardware request is issued.
          </p>
          <div>
            <button
              className="desk-button-primary w-full max-w-full sm:w-auto"
              type="submit"
              disabled={loading || updateDefaultLoanDays.isPending}
            >
              {updateDefaultLoanDays.isPending ? "Saving..." : "Save default days"}
            </button>
          </div>
          {updateDefaultLoanDays.error ? (
            <p className="text-sm text-danger">{updateDefaultLoanDays.error.message}</p>
          ) : null}
        </form>
        <div className="grid min-w-0 content-start gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold text-ink">Public inventory</h4>
            <Badge tone={publicInventoryEnabled ? "success" : "neutral"}>
              {publicInventoryEnabled ? "On" : "Off"}
            </Badge>
          </div>
          <label className="flex min-w-0 items-start gap-3 text-sm text-ink">
            <input
              className="mt-1 h-4 w-4"
              type="checkbox"
              checked={publicInventoryEnabled}
              disabled={loading || updatePublicInventory.isPending}
              onChange={(event) => updatePublicInventory.mutate(event.target.checked)}
            />
            <span className="font-semibold">Show public inventory</span>
          </label>
          <p className="text-xs text-muted">
            When off, the public inventory catalog is hidden. This does not delete any inventory data.
          </p>
          {updatePublicInventory.error ? (
            <p className="text-sm text-danger">{updatePublicInventory.error.message}</p>
          ) : null}
        </div>
      </div>
      <MakerspaceLoanPolicySettings makerspaceId={makerspace.id} />
    </div>
  );
}
