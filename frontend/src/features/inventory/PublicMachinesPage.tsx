import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { MakerspaceBrand } from "../../components/MakerspaceBrand";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { SiteFooter } from "../../components/SiteFooter";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Card, CollapsibleSection, EmptyState, Skeleton, StatusBadge } from "../../components/ui";
import type { ApiPath } from "../../generated/api";
import { StructuredApiError, tenantPublicRequest } from "../../lib/api";
import { useTenant, useTenantPath } from "../../lib/tenant";
import { formatSlug } from "./PublicInventoryParts";
import { useTenantBootstrap } from "./usePublicInventory";
import { SkipLink } from "../../components/SkipLink";

type PublicMachine = {
  name: string;
  machine_type: { name: string; icon: string };
  image_url: string | null;
  status: "idle" | "running" | "reserved" | "maintenance" | "offline";
  usage_hours: string;
};

type PaginatedMachines = {
  count: number;
  next: string | null;
  previous: string | null;
  results: PublicMachine[];
};

const PUBLIC_MACHINES_PATH: ApiPath = "/api/v1/public/{makerspace_slug}/machines";

function publicMachinesPath(slug: string) {
  return PUBLIC_MACHINES_PATH.replace("/api/v1", "").replace(
    "{makerspace_slug}", encodeURIComponent(slug),
  );
}

export function PublicMachinesPage() {
  const { slug } = useParams();
  const tenant = useTenant();
  const makerspaceSlug = tenant.mode === "single" ? tenant.slug : slug ?? "";
  const tenantPath = useTenantPath(makerspaceSlug);
  const bootstrapQuery = useTenantBootstrap(makerspaceSlug, tenant.mode === "central");
  const bootstrap = tenant.mode === "single" ? tenant.bootstrap : bootstrapQuery.data;
  const machines = useQuery({
    queryKey: ["public-machines", makerspaceSlug],
    queryFn: () => tenantPublicRequest<PaginatedMachines>(
      makerspaceSlug, publicMachinesPath(makerspaceSlug),
    ),
    retry: (count, error) => !(error instanceof StructuredApiError && error.status < 500) && count < 2,
  });

  // The public payload carries no type id, so the type name is the grouping key.
  const groups = useMemo(() => {
    const byType = new Map<string, { icon: string; machines: PublicMachine[] }>();
    for (const machine of machines.data?.results ?? []) {
      const key = machine.machine_type.name;
      const existing = byType.get(key);
      if (existing) existing.machines.push(machine);
      else byType.set(key, { icon: machine.machine_type.icon, machines: [machine] });
    }
    return [...byType.entries()].map(([name, group]) => ({ name, ...group }));
  }, [machines.data]);

  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const toggleGroup = (name: string) => setCollapsed((current) => {
    const next = new Set(current);
    if (!next.delete(name)) next.add(name);
    return next;
  });

  const displayName = bootstrap?.branding.display_name || bootstrap?.makerspace.name || formatSlug(makerspaceSlug) || "Makerspace";
  const apiError = machines.error instanceof StructuredApiError ? machines.error : null;
  const unavailable = apiError?.status === 400;
  const missing = apiError?.status === 404;
  const throttled = apiError?.status === 429;

  return <main className="desk-shell flex min-h-screen flex-col">
    <SkipLink />
    <header className="border-b border-line bg-panel">
      <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div><p className="eyebrow text-secondary-ink">Our Machines</p>
          <MakerspaceBrand name={displayName} logoUrl={bootstrap?.makerspace.logo_url} size="lg" />
        </div>
        <div className="flex flex-wrap items-center gap-2"><SpaceWorksBadge /><Link className="desk-button" to={tenantPath()}>Inventory</Link><ThemeToggle /></div>
      </div>
    </header>
    <section className="mx-auto w-full max-w-5xl flex-1 px-5 py-8" id="main-content" tabIndex={-1}>
      <div className="mb-6"><h1 className="title-page">Machines</h1><p className="mt-2 text-sm text-muted">Equipment available in this makerspace, grouped by kind.</p></div>
      {machines.isLoading ? <div className="grid gap-4" aria-label="Loading machines">{[0, 1, 2].map((item) => <Skeleton key={item} className="h-40 w-full" />)}</div> : null}
      {machines.error ? <Card><h2 className="title-panel">{throttled ? "Please slow down" : unavailable ? "Machines are not enabled" : missing ? "Makerspace not found" : "Machines are unavailable"}</h2>
        <p className="mt-2 text-sm text-muted">{throttled ? "Too many requests were made. Wait a moment and retry." : apiError?.detail ?? machines.error.message}</p>
        {!missing && !unavailable ? <button className="desk-button mt-4" type="button" onClick={() => machines.refetch()}>Retry</button> : null}
      </Card> : null}
      {machines.data && !groups.length ? <div className="[&>div]:border-secondary"><EmptyState title="No machines listed" description="This makerspace has not published any machines yet." /></div> : null}
      {groups.length ? <div className="grid gap-4">{groups.map((group) => (
        <CollapsibleSection key={group.name} title={group.name} icon={group.icon || null}
          count={group.machines.length} open={!collapsed.has(group.name)}
          onToggle={() => toggleGroup(group.name)}>
          <ul className="grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-3">
            {group.machines.map((machine) => (
              <li key={machine.name} className="overflow-hidden rounded-xl border border-line bg-bg">
                {/* Decorative: the machine name is rendered right below it. */}
                {machine.image_url ? <img src={machine.image_url} alt="" loading="lazy" className="h-36 w-full object-cover" /> : null}
                <div className="grid gap-2 p-3">
                  <h3 className="title-section truncate">{machine.name}</h3>
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={machine.status} />
                    <span className="eyebrow">{machine.usage_hours} h logged</span>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </CollapsibleSection>
      ))}</div> : null}
    </section>
    <SiteFooter />
  </main>;
}
