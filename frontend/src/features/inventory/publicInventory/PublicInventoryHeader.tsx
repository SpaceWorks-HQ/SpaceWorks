import { Link } from "react-router-dom";

import { MakerspaceBrand } from "../../../components/MakerspaceBrand";
import { MakerspaceMapLink } from "../../../components/MakerspaceMapLink";
import { SpaceWorksBadge } from "../../../components/SpaceWorksLogo";
import { ThemeToggle } from "../../../components/ThemeToggle";
import { ChartIcon, UserIcon } from "../../../components/icons";
import { IconLink } from "../../../components/ui";
import type { TenantBootstrap } from "../../../lib/api";

type PublicInventoryHeaderProps = {
  displayName: string;
  makerspace: TenantBootstrap["makerspace"] | undefined;
  modules: Set<string>;
  tenantPath: (subpath?: string) => string;
  listedCount: number | undefined;
};

export function PublicInventoryHeader({
  displayName,
  makerspace,
  modules,
  tenantPath,
  listedCount,
}: PublicInventoryHeaderProps) {
  return (
    <header className="material-chrome border-b border-line">
      <div className="mx-auto flex max-w-screen-2xl flex-col gap-2 px-5 py-4 sm:px-8">
        <p className="eyebrow text-secondary-ink">
          Public Inventory
        </p>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <h1 className="title-page">
              <MakerspaceBrand
                name={displayName}
                logoUrl={makerspace?.logo_url}
                size="xl"
              />
            </h1>
            <p className="mt-1 text-sm text-muted">
              Shared tools and equipment published by this makerspace.
            </p>
            <MakerspaceMapLink
              makerspace={makerspace}
              className="mt-1"
            />
          </div>
          <div className="flex flex-col items-end gap-2">
            <div className="flex items-center justify-end gap-2">
              {makerspace?.public_stats_enabled ? (
                <IconLink label="Stats" to={tenantPath("stats")}>
                  <ChartIcon />
                </IconLink>
              ) : null}
              <ThemeToggle variant="icon" />
              <IconLink label="Staff login" to="/admin">
                <UserIcon />
              </IconLink>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <SpaceWorksBadge />
              <div className="rounded-lg border border-secondary bg-secondary/15 px-3 py-2 font-mono text-sm text-secondary-ink">
                {listedCount ?? "-"} listed items
              </div>
              {modules.has("printing") ? (
                <Link className="desk-button" to={tenantPath("print")}>
                  Request a 3D print
                </Link>
              ) : null}
              {modules.has("events") ? (
                <Link className="desk-button" to={tenantPath("events")}>
                  Events
                </Link>
              ) : null}
              {modules.has("machines") ? (
                <Link className="desk-button" to={tenantPath("machines")}>
                  Machines
                </Link>
              ) : null}
              {modules.has("bookings") ? (
                <Link className="desk-button" to={tenantPath("bookings")}>
                  Book a space
                </Link>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
