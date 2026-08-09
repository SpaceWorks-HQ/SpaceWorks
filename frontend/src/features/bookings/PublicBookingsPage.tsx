import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { MakerspaceBrand } from "../../components/MakerspaceBrand";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { SiteFooter } from "../../components/SiteFooter";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Badge, Card, EmptyState, Skeleton } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import { useTenant, useTenantPath } from "../../lib/tenant";
import { formatSlug } from "../inventory/PublicInventoryParts";
import { useTenantBootstrap } from "../inventory/usePublicInventory";
import { PublicBookingForm } from "./PublicBookingForm";
import { usePublicSpaces, type PublicBookableSpace } from "./publicBookingsApi";
import { SkipLink } from "../../components/SkipLink";

const KIND_LABELS: Record<PublicBookableSpace["kind"], string> = {
  dev_room: "Development room",
  bench: "Bench",
  meeting: "Meeting room",
  other: "Other",
};

export function PublicBookingsPage() {
  const { slug } = useParams();
  const tenant = useTenant();
  const makerspaceSlug = tenant.mode === "single" ? tenant.slug : slug ?? "";
  const tenantPath = useTenantPath(makerspaceSlug);
  const bootstrapQuery = useTenantBootstrap(makerspaceSlug, tenant.mode === "central");
  const bootstrap = tenant.mode === "single" ? tenant.bootstrap : bootstrapQuery.data;
  const modules = tenant.mode === "single" ? tenant.modules : new Set(bootstrap?.modules ?? []);
  const spaces = usePublicSpaces(makerspaceSlug);
  const [activeToken, setActiveToken] = useState<string | null>(null);
  const apiError = spaces.error instanceof StructuredApiError ? spaces.error : null;
  const unavailable = apiError?.status === 400;
  const missing = apiError?.status === 404;
  const throttled = apiError?.status === 429;
  const displayName = bootstrap?.branding.display_name || bootstrap?.makerspace.name || formatSlug(makerspaceSlug) || "Makerspace";

  return (
    <main className="desk-shell flex min-h-screen flex-col">
      <SkipLink />
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-3 px-5 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-accent-ink">Space bookings</p>
            <MakerspaceBrand name={displayName} logoUrl={bootstrap?.makerspace.logo_url} size="lg" />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <SpaceWorksBadge />
            <Link className="desk-button" to={tenantPath()}>Inventory</Link>
            {modules.has("events") ? <Link className="desk-button" to={tenantPath("events")}>Events</Link> : null}
            <ThemeToggle />
          </div>
        </div>
      </header>
      <section className="mx-auto w-full max-w-5xl flex-1 px-5 py-8" id="main-content" tabIndex={-1}>
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-ink">Book a makerspace</h1>
          <p className="mt-2 text-sm text-muted">Choose a public space, check published bookings, and request a time.</p>
        </div>
        {spaces.isLoading ? <div className="grid gap-4" aria-label="Loading spaces">{[0, 1, 2].map((item) => <Skeleton key={item} className="h-64 w-full" />)}</div> : null}
        {spaces.error ? (
          <Card>
            <h2 className="text-lg font-semibold text-ink">{throttled ? "Please slow down" : unavailable ? "Bookings are not enabled" : missing ? "Makerspace not found" : "Spaces are unavailable"}</h2>
            <p className="mt-2 text-sm text-muted">{throttled ? "Too many requests were made. Wait a moment and retry." : apiError?.detail ?? spaces.error.message}</p>
            {!missing && !unavailable ? <button className="desk-button mt-4" type="button" onClick={() => spaces.refetch()}>Retry</button> : null}
          </Card>
        ) : null}
        {spaces.data && !spaces.data.length ? <EmptyState title="No spaces available" description="Public bookable spaces will appear here when they are enabled." /> : null}
        {spaces.data?.length ? (
          <div className="grid gap-5">
            {spaces.data.map((space) => {
              const open = activeToken === space.public_token;
              return (
                <article key={space.public_token} className="desk-panel overflow-hidden">
                  {space.image_url ? <img className="h-52 w-full border-b border-line object-cover" src={space.image_url} alt="" loading="lazy" /> : null}
                  <div className="p-5">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h2 className="text-xl font-bold text-ink">{space.name}</h2>
                        {space.location ? <p className="mt-1 text-sm text-muted">{space.location}</p> : null}
                      </div>
                      <Badge tone="neutral">{KIND_LABELS[space.kind]}</Badge>
                    </div>
                    {space.description ? <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-ink">{space.description}</p> : null}
                    <dl className="mt-4 flex flex-wrap gap-6 text-sm">
                      <div><dt className="text-xs font-semibold uppercase text-muted">Capacity</dt><dd className="font-semibold text-ink">{space.capacity === 0 ? "Not specified" : space.capacity}</dd></div>
                      <div><dt className="text-xs font-semibold uppercase text-muted">Confirmation</dt><dd className="font-semibold text-ink">{space.approval_mode === "approve" ? "Staff approval required" : "Instant when available"}</dd></div>
                    </dl>
                    <p className="mt-3 text-sm text-muted">{space.approval_mode === "approve" ? "Your request stays pending until makerspace staff review it." : "A non-overlapping slot is confirmed immediately."}</p>
                    <button className="desk-button-primary mt-4" type="button" aria-expanded={open} onClick={() => setActiveToken(open ? null : space.public_token)}>{open ? "Close booking form" : "Choose a time"}</button>
                    {open ? <div className="mt-5"><PublicBookingForm key={space.public_token} makerspaceSlug={makerspaceSlug} space={space} /></div> : null}
                  </div>
                </article>
              );
            })}
          </div>
        ) : null}
      </section>
      <SiteFooter />
    </main>
  );
}
