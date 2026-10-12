"""Claim policies for routes mounted below ``/api/v1/public/``."""

from apps.accounts.claim_route_types import (
    AnonymousRead,
    Allowed,
    BODY_OBJECT,
    PUBLIC_TOKEN,
    ReadOnly,
    Refused,
    SLUG,
)


def _anonymous(name):
    return {
        (name, "GET"): AnonymousRead(),
        (name, "HEAD"): AnonymousRead(),
        (name, "OPTIONS"): AnonymousRead(),
    }


PUBLIC_CLAIM_ROUTES = {
    ('member-booking-reschedule', 'POST'): Allowed(tenant=SLUG, audited=True),
    ('member-booking-reschedule', 'OPTIONS'): AnonymousRead(),
    **{('member-booking-feed-settings', method): Refused(
        'claim sessions cannot manage durable bearer credentials'
    ) for method in ('GET', 'HEAD', 'POST', 'DELETE')},
    ('member-booking-feed-settings', 'OPTIONS'): AnonymousRead(),
    **_anonymous('public-booking-feed'),
    ('member-booking-list', 'GET'): ReadOnly(tenant=SLUG),
    ('member-booking-list', 'HEAD'): ReadOnly(tenant=SLUG),
    ('member-booking-list', 'OPTIONS'): AnonymousRead(),
    ('member-booking-cancel', 'POST'): Allowed(tenant=SLUG, audited=True),
    ('member-booking-cancel', 'OPTIONS'): AnonymousRead(),
    **_anonymous("public-membership-admission"),
    **_anonymous("public-machines"),
    **_anonymous("public-machine-intake"),
    **_anonymous("public-machine-details"),
    **_anonymous("public-machine-detail"),
    ("public-machine-service-request-submit", "POST"): Allowed(
        tenant=BODY_OBJECT, audited=True
    ),
    ("public-machine-service-request-submit", "OPTIONS"): AnonymousRead(),
    **_anonymous("public-printer-service-queues"),
    **_anonymous("public-printer-service-pools"),
    ("public-printer-service-upload", "POST"): Allowed(tenant=SLUG, audited=True),
    ("public-printer-service-upload", "OPTIONS"): AnonymousRead(),
    ("public-printer-service-request", "POST"): Allowed(tenant=SLUG, audited=True),
    ("public-printer-service-request", "OPTIONS"): AnonymousRead(),
    **_anonymous("public-printer-service-status"),
    **_anonymous("public-event-list"),
    **_anonymous("public-event-detail"),
    # The organization directory is deployment-global read-only presentation; a walk-in
    # claim session reads it exactly like any anonymous visitor.
    **_anonymous("public-organization-detail"),
    **_anonymous("public-organization-events"),
    **_anonymous("public-event-calendar"),
    **_anonymous("public-event-calendar-feed"),
    ("public-event-register", "POST"): Allowed(
        tenant=PUBLIC_TOKEN, audited=True
    ),
    ("public-event-register", "OPTIONS"): AnonymousRead(),
    **_anonymous("public-event-feedback"),
    ("public-event-feedback", "POST"): Allowed(
        tenant=PUBLIC_TOKEN, audited=True
    ),
    **_anonymous("public-bookable-space-list"),
    **_anonymous("public-space-availability"),
    ("public-booking-submit", "POST"): Allowed(
        tenant=PUBLIC_TOKEN, audited=True
    ),
    ("public-booking-submit", "OPTIONS"): AnonymousRead(),
    ("presence-start", "POST"): Allowed(tenant=SLUG, audited=True),
    ("presence-start", "OPTIONS"): AnonymousRead(),
    ("presence-current", "GET"): ReadOnly(tenant=SLUG),
    ("presence-current", "HEAD"): ReadOnly(tenant=SLUG),
    ("presence-current", "OPTIONS"): AnonymousRead(),
    ("presence-end", "POST"): Allowed(tenant=SLUG, audited=True),
    ("presence-end", "OPTIONS"): AnonymousRead(),
    **_anonymous("v1:public-makerspaces"),
    **_anonymous("v1:public-inventory"),
    **_anonymous("v1:public-makerspace-stats"),
    **_anonymous("v1:public-inventory-categories"),
    **_anonymous("v1:public-inventory-detail"),
    ("v1:public-inventory-watch", "POST"): Allowed(tenant=SLUG, audited=True),
    ("v1:public-inventory-watch", "DELETE"): Allowed(tenant=SLUG, audited=True),
    ("v1:public-inventory-watch", "OPTIONS"): AnonymousRead(),
    ("public-membership-request", "POST"): Refused(
        "walk-ins cannot satisfy verified-email eligibility"
    ),
    ("public-membership-request", "OPTIONS"): AnonymousRead(),
    # A walk-in already holds a membership claim; asking to be invited makes no sense
    # from inside one, and the anonymous path stays open to everyone else.
    ("public-invitation-request", "POST"): Refused(
        "walk-ins already hold a membership; invitation requests are for outsiders"
    ),
    ("public-invitation-request", "OPTIONS"): AnonymousRead(),
    ("hardware_requests:request-submit", "POST"): Allowed(
        tenant=SLUG, audited=True
    ),
    ("hardware_requests:request-submit", "OPTIONS"): AnonymousRead(),
    ("hardware_requests:public-tool-evidence-url", "POST"): Allowed(
        tenant=SLUG, audited=True
    ),
    ("hardware_requests:public-tool-evidence-url", "OPTIONS"): AnonymousRead(),
    ("hardware_requests:public-tool-checklist", "POST"): Allowed(
        tenant=SLUG, audited=False
    ),
    ("hardware_requests:public-tool-checklist", "OPTIONS"): AnonymousRead(),
    ("hardware_requests:public-tool-checkout", "POST"): Allowed(
        tenant=SLUG, audited=True
    ),
    ("hardware_requests:public-tool-checkout", "OPTIONS"): AnonymousRead(),
    ("hardware_requests:public-tool-return", "POST"): Allowed(
        tenant=SLUG, audited=True
    ),
    ("hardware_requests:public-tool-return", "OPTIONS"): AnonymousRead(),
    **_anonymous("hardware_requests:request-status"),
}
