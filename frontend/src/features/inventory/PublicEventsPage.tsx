import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { MakerspaceBrand } from "../../components/MakerspaceBrand";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { SiteFooter } from "../../components/SiteFooter";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Card, EmptyState, Skeleton, StatusBadge } from "../../components/ui";
import type { ApiPath } from "../../generated/api";
import { StructuredApiError, tenantPublicRequest } from "../../lib/api";
import { useTenant, useTenantPath } from "../../lib/tenant";
import { EventRegistrationForm } from "./EventRegistrationForm";
import { formatSlug } from "./PublicInventoryParts";
import { useTenantBootstrap } from "./usePublicInventory";

type PublicEvent = {
  public_token: string;
  title: string;
  description: string;
  starts_at: string;
  ends_at: string;
  location: string;
  capacity: number | null;
  availability: "Available" | "Limited" | "Full";
  image_url: string | null;
  status: "published";
};

const PUBLIC_EVENTS_PATH: ApiPath = "/api/v1/public/{makerspace_slug}/events/";

function publicEventsPath(slug: string) {
  return PUBLIC_EVENTS_PATH.replace("/api/v1", "").replace("{makerspace_slug}", encodeURIComponent(slug));
}

function eventTime(event: PublicEvent) {
  const options: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeStyle: "short" };
  return `${new Date(event.starts_at).toLocaleString(undefined, options)} – ${new Date(event.ends_at).toLocaleString(undefined, options)}`;
}

export function PublicEventsPage() {
  const { slug } = useParams();
  const tenant = useTenant();
  const makerspaceSlug = tenant.mode === "single" ? tenant.slug : slug ?? "";
  const tenantPath = useTenantPath(makerspaceSlug);
  const bootstrapQuery = useTenantBootstrap(makerspaceSlug, tenant.mode === "central");
  const bootstrap = tenant.mode === "single" ? tenant.bootstrap : bootstrapQuery.data;
  const [activeToken, setActiveToken] = useState<string | null>(null);
  const events = useQuery({
    queryKey: ["public-events", makerspaceSlug],
    queryFn: () => tenantPublicRequest<PublicEvent[]>(makerspaceSlug, publicEventsPath(makerspaceSlug)),
    retry: (count, error) => !(error instanceof StructuredApiError && error.status < 500) && count < 2,
  });
  const displayName = bootstrap?.branding.display_name || bootstrap?.makerspace.name || formatSlug(makerspaceSlug) || "Makerspace";
  const apiError = events.error instanceof StructuredApiError ? events.error : null;
  const unavailable = apiError?.status === 400;
  const missing = apiError?.status === 404;
  const throttled = apiError?.status === 429;

  return <main className="desk-shell flex min-h-screen flex-col">
    <header className="border-b border-line bg-panel">
      <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div><p className="text-xs font-semibold uppercase tracking-wide text-accent-ink">Public Events</p>
          <MakerspaceBrand name={displayName} logoUrl={bootstrap?.makerspace.logo_url} size="lg" />
        </div>
        <div className="flex flex-wrap items-center gap-2"><SpaceWorksBadge /><Link className="desk-button" to={tenantPath()}>Inventory</Link><ThemeToggle /></div>
      </div>
    </header>
    <section className="mx-auto w-full max-w-5xl flex-1 px-5 py-8">
      <div className="mb-6"><h1 className="text-3xl font-bold text-ink">Upcoming events</h1><p className="mt-2 text-sm text-muted">Register for workshops, meetups, and community sessions.</p></div>
      {events.isLoading ? <div className="grid gap-4" aria-label="Loading events">{[0, 1, 2].map((item) => <Skeleton key={item} className="h-52 w-full" />)}</div> : null}
      {events.error ? <Card><h2 className="text-lg font-semibold text-ink">{throttled ? "Please slow down" : unavailable ? "Events are not enabled" : missing ? "Makerspace not found" : "Events are unavailable"}</h2>
        <p className="mt-2 text-sm text-muted">{throttled ? "Too many requests were made. Wait a moment and retry." : apiError?.detail ?? events.error.message}</p>
        {!missing && !unavailable ? <button className="desk-button mt-4" type="button" onClick={() => events.refetch()}>Retry</button> : null}
      </Card> : null}
      {events.data && !events.data.length ? <EmptyState title="No upcoming events" description="New public events will appear here when they are published." /> : null}
      {events.data?.length ? <div className="grid gap-5">{events.data.map((item) => {
        const unlimited = item.capacity === 0 || item.capacity === null;
        const waitlist = item.availability === "Full";
        const open = activeToken === item.public_token;
        return <article key={item.public_token} className="desk-panel overflow-hidden p-0">
          {/* Decorative: the title beside it already names the event, so alt is empty
              rather than a duplicate announcement for screen-reader users. */}
          {item.image_url ? <img src={item.image_url} alt="" loading="lazy" className="h-48 w-full object-cover sm:h-56" /> : null}
          <div className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h2 className="text-xl font-bold text-ink">{item.title}</h2><p className="mt-1 text-sm text-muted"><time dateTime={item.starts_at}>{eventTime(item)}</time></p>{item.location ? <p className="mt-1 text-sm text-muted">{item.location}</p> : null}</div><StatusBadge status={item.status} /></div>
          {item.description ? <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-ink">{item.description}</p> : null}
          <dl className="mt-4 flex flex-wrap gap-4 text-sm"><div><dt className="text-xs font-semibold uppercase text-muted">Capacity</dt><dd className="font-semibold text-ink">{unlimited ? "Unlimited" : item.capacity}</dd></div><div><dt className="text-xs font-semibold uppercase text-muted">Availability</dt><dd className="font-semibold text-ink">{item.availability}</dd></div></dl>
          <button className="desk-button-primary mt-4" type="button" aria-expanded={open} onClick={() => setActiveToken(open ? null : item.public_token)}>{open ? "Close form" : waitlist ? "Join waitlist" : "Register"}</button>
          {open ? <div className="mt-4"><EventRegistrationForm key={item.public_token} makerspaceSlug={makerspaceSlug} publicToken={item.public_token} waitlist={waitlist} /></div> : null}
          </div>
        </article>;
      })}</div> : null}
    </section>
    <SiteFooter />
  </main>;
}
