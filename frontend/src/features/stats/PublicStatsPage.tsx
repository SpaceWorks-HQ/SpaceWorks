import { Link, useParams } from "react-router-dom";

import { MakerspaceBrand } from "../../components/MakerspaceBrand";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Card } from "../../components/ui/Card";
import { Spinner } from "../../components/ui/Spinner";
import { useTenant, useTenantPath } from "../../lib/tenant";
import { formatSlug } from "../inventory/PublicInventoryParts";
import { useTenantBootstrap } from "../inventory/usePublicInventory";
import { usePublicStats, type PublicStatsResponse } from "./api";
import { SkipLink } from "../../components/SkipLink";
import {
  CurrentLoansSection,
  HardwareSection,
  PrintingSection,
} from "./StatsSections";

export function PublicStatsPage() {
  const { slug } = useParams();
  const tenant = useTenant();
  const makerspaceSlug = tenant.mode === "single" ? tenant.slug : slug ?? "";
  const tenantPath = useTenantPath(makerspaceSlug);
  const bootstrapQuery = useTenantBootstrap(
    makerspaceSlug,
    tenant.mode === "central",
  );
  const statsQuery = usePublicStats(makerspaceSlug);
  const bootstrap = tenant.mode === "single" ? tenant.bootstrap : bootstrapQuery.data;
  const displayName =
    bootstrap?.branding.display_name ||
    bootstrap?.makerspace.name ||
    formatSlug(makerspaceSlug) ||
    "Makerspace";

  return (
    <main className="desk-shell">
      <SkipLink />
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex max-w-screen-2xl flex-col gap-4 px-5 py-6 sm:px-8">
          <p className="eyebrow text-secondary-ink">
            Public Stats
          </p>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <h1 className="title-page">
                <MakerspaceBrand
                  name={displayName}
                  logoUrl={bootstrap?.makerspace.logo_url}
                  size="lg"
                />
              </h1>
              <p className="mt-2 text-sm text-muted">
                Live community activity from the public catalog.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <SpaceWorksBadge />
              <Link className="desk-button" to={tenantPath()}>
                Catalog
              </Link>
              <ThemeToggle />
              <Link className="desk-button" to="/admin">
                Staff login
              </Link>
            </div>
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-screen-2xl space-y-5 px-5 py-6 sm:px-8" id="main-content" tabIndex={-1}>
        {statsQuery.isLoading ? <LoadingState /> : null}

        {statsQuery.isError ? <ErrorState /> : null}

        {statsQuery.data && isEmptyStats(statsQuery.data) ? <EmptyState /> : null}

        {statsQuery.data && !isEmptyStats(statsQuery.data) ? (
          <>
            {statsQuery.data.printing ? (
              <PrintingSection printing={statsQuery.data.printing} />
            ) : null}
            <HardwareSection hardware={statsQuery.data.hardware} />
            <CurrentLoansSection loans={statsQuery.data.current_loans} />
          </>
        ) : null}
      </section>
    </main>
  );
}

function LoadingState() {
  return (
    <div className="grid min-h-64 place-items-center">
      <Spinner />
    </div>
  );
}

function ErrorState() {
  return (
    <Card className="mx-auto max-w-lg border-secondary text-center">
      <h2 className="title-panel">Stats not available</h2>
      <p className="mt-2 text-sm leading-6 text-muted">
        This makerspace has its public stats page turned off, or it may not exist.
      </p>
    </Card>
  );
}

function EmptyState() {
  return (
    <Card className="mx-auto max-w-lg border-secondary text-center">
      <h2 className="title-panel">
        No public activity yet.
      </h2>
      <p className="mt-2 text-sm leading-6 text-muted">
        Stats will appear after this makerspace publishes tools or records public
        loans and print activity.
      </p>
    </Card>
  );
}

function isEmptyStats(stats: PublicStatsResponse) {
  return (
    stats.printing === null &&
    stats.hardware.library.library_size === 0 &&
    stats.hardware.most_popular.length === 0 &&
    stats.hardware.tools_out.length === 0 &&
    stats.hardware.recently_added.length === 0 &&
    stats.current_loans.length === 0
  );
}
