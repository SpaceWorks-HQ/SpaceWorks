import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { MakerspaceBrand } from "../../components/MakerspaceBrand";
import { SkipLink } from "../../components/SkipLink";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { SiteFooter } from "../../components/SiteFooter";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Card, EmptyState, Skeleton } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import {
  usePublicOrganization,
  usePublicOrganizationEvents,
  type OrganizationPublicEvent,
} from "./publicOrganizationsApi";

function dateRange(event: OrganizationPublicEvent) {
  const options: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeStyle: "short" };
  return `${new Date(event.starts_at).toLocaleString(undefined, options)} – ${new Date(event.ends_at).toLocaleString(undefined, options)}`;
}

export function PublicOrganizationPage() {
  const { organizationSlug = "" } = useParams();
  const [page, setPage] = useState(1);
  const organization = usePublicOrganization(organizationSlug);
  const events = usePublicOrganizationEvents(organizationSlug, page);
  const missing = organization.error instanceof StructuredApiError && organization.error.status === 404;

  return (
    <main className="desk-shell flex min-h-screen flex-col">
      <SkipLink />
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-4">
          {organization.data ? (
            <MakerspaceBrand name={organization.data.name} logoUrl={organization.data.logo_url} size="lg" />
          ) : <SpaceWorksBadge />}
          <div className="flex items-center gap-2">
            <Link className="desk-button" to="/">Directory</Link>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <section className="mx-auto w-full max-w-6xl flex-1 px-5 py-8" id="main-content" tabIndex={-1}>
        {organization.isLoading ? <Skeleton className="h-40 w-full" /> : null}
        {organization.error ? (
          <EmptyState
            title={missing ? "Organization not found" : "Organization unavailable"}
            description={missing ? "This organization does not have a public profile." : organization.error.message}
          />
        ) : null}
        {organization.data ? (
          <>
            <div className="desk-panel p-6">
              <p className="eyebrow text-secondary-ink">Organization directory</p>
              <h1 className="title-page mt-2">{organization.data.name}</h1>
              {organization.data.description ? <p className="mt-4 max-w-3xl whitespace-pre-wrap text-sm leading-6 text-ink">{organization.data.description}</p> : null}
              {organization.data.website ? (
                <a className="desk-button-secondary mt-4" href={organization.data.website} rel="noreferrer" target="_blank">
                  Visit website
                </a>
              ) : null}
            </div>

            <section className="mt-8" aria-labelledby="organization-events-heading">
              <div className="mb-4">
                <p className="eyebrow text-accent-ink">Across makerspaces</p>
                <h2 className="title-panel mt-1" id="organization-events-heading">Upcoming events</h2>
              </div>
              {events.isLoading ? <div className="grid gap-4" aria-label="Loading organization events">{[0, 1, 2].map((item) => <Skeleton key={item} className="h-52 w-full" />)}</div> : null}
              {events.error ? (
                <Card>
                  <h3 className="title-section">Events are unavailable</h3>
                  <p className="mt-2 text-sm text-muted">{events.error.message}</p>
                  <button className="desk-button mt-4" type="button" onClick={() => events.refetch()}>Retry</button>
                </Card>
              ) : null}
              {events.data && !events.data.results.length ? (
                <EmptyState title="No upcoming events" description="Published events will appear here." />
              ) : null}
              {events.data?.results.length ? (
                <div className="grid gap-5 md:grid-cols-2">
                  {events.data.results.map((event) => (
                    <article className="desk-panel overflow-hidden p-0" key={event.public_token}>
                      {event.image_url ? <img className="h-44 w-full object-cover" src={event.image_url} alt="" loading="lazy" /> : null}
                      <div className="p-5">
                        <p className="eyebrow text-secondary-ink">Hosted by {event.host.name}</p>
                        <h3 className="title-section mt-2">{event.title}</h3>
                        <p className="mt-2 font-mono text-xs text-muted"><time dateTime={event.starts_at}>{dateRange(event)}</time></p>
                        {event.location ? <p className="mt-1 text-sm text-muted">{event.location}</p> : null}
                        {event.description ? <p className="mt-3 line-clamp-3 text-sm leading-6 text-ink">{event.description}</p> : null}
                        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                          <span className="chip chip-available">{event.availability}</span>
                          <Link className="desk-button-primary" to={`/m/${event.host.slug}/events`}>
                            Register at {event.host.name}
                          </Link>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              ) : null}
              {events.data ? (
                <div className="mt-5 flex items-center justify-between gap-3">
                  <button className="desk-button" type="button" disabled={!events.data.previous} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</button>
                  <span className="font-mono text-xs text-muted">Page {page} · {events.data.count} events</span>
                  <button className="desk-button" type="button" disabled={!events.data.next} onClick={() => setPage((value) => value + 1)}>Next</button>
                </div>
              ) : null}
            </section>
          </>
        ) : null}
      </section>
      <SiteFooter />
    </main>
  );
}
