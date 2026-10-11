import { useState } from "react";
import { downloadEventCalendar } from "../events/eventCalendar";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useLocation, useParams } from "react-router-dom";
import { PageMetadata } from "../../components/PageMetadata";
import { SkipLink } from "../../components/SkipLink";
import { StructuredApiError, tenantPublicRequest } from "../../lib/api";
import { useTenant, useTenantPath } from "../../lib/tenant";
import { EventRegistrationForm } from "./EventRegistrationForm";
import { EventPrice } from "../events/EventPrice";
import type { PublicEventDetail } from "../events/eventTicketTypes";

/** WP2 mounts this component on both central and tenant-domain event routes. */
export function PublicEventDetailPage() {
  const { slug, publicToken } = useParams();
  const tenant = useTenant();
  const makerspaceSlug = tenant.mode === "single" ? tenant.slug : slug ?? "";
  const tenantPath = useTenantPath(makerspaceSlug);
  const location = useLocation();
  const [shareError, setShareError] = useState("");
  const calendar = useMutation({ mutationFn: (item: PublicEventDetail) => downloadEventCalendar(makerspaceSlug, item) });
  const eventQuery = useQuery({
    queryKey: ["public-event", makerspaceSlug, publicToken],
    staleTime: 0, gcTime: 0, refetchOnMount: "always",
    queryFn: () => tenantPublicRequest<PublicEventDetail>(makerspaceSlug, `/public/${encodeURIComponent(makerspaceSlug)}/events/${encodeURIComponent(publicToken ?? "")}/`),
    enabled: Boolean(makerspaceSlug && publicToken),
    retry: (count, error) => !(error instanceof StructuredApiError && error.status < 500) && count < 2,
  });
  const event = eventQuery.error ? undefined : eventQuery.data;
  const error = eventQuery.error instanceof StructuredApiError ? eventQuery.error : null;
  return <main className="desk-shell min-h-screen p-5">
    <SkipLink />
    <div id="main-content" className="mx-auto grid max-w-3xl gap-4">
      <Link className="desk-button w-fit" to={tenantPath("events")}>All events</Link>
      {eventQuery.isLoading ? <p role="status">Loading event…</p> : null}
      {eventQuery.error ? <p role="alert">{error?.status === 404 ? "Event not found." : error?.status === 400 ? "Events are unavailable at this makerspace." : "Unable to load this event."}</p> : null}
      {event ? <>
        <PageMetadata title={event.title} description={event.description.slice(0, 200)} path={location.pathname} image={event.image_url} />
        {event.image_url ? <img src={event.image_url} alt="" className="max-h-80 w-full rounded-xl object-cover" /> : null}
        <h1 className="title-page">{event.title}</h1>
        <p>{new Date(event.starts_at).toLocaleString()} · {event.location}</p>
        {event.category ? <p className="text-sm text-muted">{event.category.name}</p> : null}
        {event.tags?.length ? <p className="text-sm text-muted">{event.tags.join(" · ")}</p> : null}
        <p className="whitespace-pre-wrap">{event.description}</p>
        <EventPrice amount={event.payment_amount} currency={event.currency} tickets={event.ticket_types} ticketRequired={event.ticket_selection_required} />
        <button className="desk-button w-fit" type="button" disabled={calendar.isPending} onClick={() => calendar.mutate(event)}>Add to calendar</button>
        {calendar.error ? <p role="alert">Could not download this calendar.</p> : null}
        <button className="desk-button w-fit" type="button" onClick={async () => { setShareError(""); try { if (navigator.share) await navigator.share({ title: event.title, url: window.location.href }); else await navigator.clipboard.writeText(window.location.href); } catch { setShareError("Could not share this event."); } }}>Share event</button>
        {shareError ? <p role="alert">{shareError}</p> : null}
        {event.registration_open ? <EventRegistrationForm key={`${makerspaceSlug}:${event.public_token}`} makerspaceSlug={makerspaceSlug} publicToken={event.public_token} waitlist={event.availability === "Full"} approvalRequired={event.registration_requires_approval} customForm={event.custom_form} audience={event.registration_audience} tickets={event.ticket_types} ticketRequired={event.ticket_selection_required} promoEnabled={event.promo_codes_enabled} currency={event.currency} /> : <p>Registration is closed.</p>}
      </> : null}
    </div>
  </main>;
}
