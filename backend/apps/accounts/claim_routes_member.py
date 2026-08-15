"""Claim policies for member and membership routes."""

from apps.accounts.claim_route_types import (
    AnonymousRead,
    Allowed,
    ID,
    LocallyFiltered,
    ReadOnly,
    Refused,
    RowOwnership,
)


def _options(name):
    return {(name, "OPTIONS"): AnonymousRead()}


MEMBER_CLAIM_ROUTES = {
    ("member-archived-payments", "GET"): Refused(
        "tenantless archived-payment discovery cannot satisfy single tenancy",
        ownership=RowOwnership.MIXED_REFUSED,
    ),
    ("member-archived-payments", "HEAD"): Refused(
        "tenantless archived-payment discovery cannot satisfy single tenancy",
        ownership=RowOwnership.MIXED_REFUSED,
    ),
    **_options("member-archived-payments"),
    ("my-memberships", "GET"): Refused("the membership list spans tenants"),
    ("my-memberships", "HEAD"): Refused("the membership list spans tenants"),
    **_options("my-memberships"),
    ("membership-invitations", "GET"): Refused("claim sessions cannot claim invitations"),
    ("membership-invitations", "HEAD"): Refused("claim sessions cannot claim invitations"),
    **_options("membership-invitations"),
    ("membership-invitation-claim", "POST"): Refused("claim sessions cannot claim invitations"),
    **_options("membership-invitation-claim"),
    ("membership-invitation-claim-legacy", "POST"): Refused(
        "claim sessions cannot claim invitations"
    ),
    **_options("membership-invitation-claim-legacy"),
    ("member-waiver", "GET"): ReadOnly(tenant=ID),
    ("member-waiver", "HEAD"): ReadOnly(tenant=ID),
    **_options("member-waiver"),
    ("member-waiver-accept", "POST"): Refused(
        "claim waiver acceptance must be witnessed by authenticated staff"
    ),
    **_options("member-waiver-accept"),
    ("member-activity", "GET"): LocallyFiltered(tenant=ID),
    ("member-activity", "HEAD"): LocallyFiltered(tenant=ID),
    **_options("member-activity"),
    ("member-payment-history", "GET"): LocallyFiltered(tenant=ID),
    ("member-payment-history", "HEAD"): LocallyFiltered(tenant=ID),
    **_options("member-payment-history"),
    ("member-payment-checkout", "POST"): Allowed(
        tenant=ID,
        audited=True,
        ownership=RowOwnership.LOCAL_OWNER_ENFORCED,
    ),
    **_options("member-payment-checkout"),
    ("member-payment-mobile-intent", "POST"): Refused(
        "native payment intent requires an attested device grant"
    ),
    **_options("member-payment-mobile-intent"),
    ("member-referrals", "POST"): Refused("walk-ins cannot delegate membership eligibility"),
    **_options("member-referrals"),
    # Profile payloads include event activity. D5 applies the claim-local event filter;
    # D3 records that mixed ownership so it cannot be mistaken for a plain local read.
    ("member-profile", "GET"): LocallyFiltered(tenant=ID),
    ("member-profile", "HEAD"): LocallyFiltered(tenant=ID),
    ("member-profile", "PUT"): Allowed(
        tenant=ID, audited=True, ownership=RowOwnership.LOCALLY_FILTERED
    ),
    **_options("member-profile"),
    ("member-profile-image", "POST"): Allowed(tenant=ID, audited=False),
    ("member-profile-image", "PUT"): Allowed(
        tenant=ID, audited=True, ownership=RowOwnership.LOCALLY_FILTERED
    ),
    ("member-profile-image", "DELETE"): Allowed(
        tenant=ID, audited=True, ownership=RowOwnership.LOCALLY_FILTERED
    ),
    **_options("member-profile-image"),
    ("member-directory", "GET"): ReadOnly(tenant=ID),
    ("member-directory", "HEAD"): ReadOnly(tenant=ID),
    **_options("member-directory"),
    ("member-directory-detail", "GET"): LocallyFiltered(tenant=ID),
    ("member-directory-detail", "HEAD"): LocallyFiltered(tenant=ID),
    **_options("member-directory-detail"),
    ("member-collaborative-events", "GET"): Refused(
        "collaborative event lists contain foreign-owned rows",
        ownership=RowOwnership.MIXED_REFUSED,
    ),
    ("member-collaborative-events", "HEAD"): Refused(
        "collaborative event lists contain foreign-owned rows",
        ownership=RowOwnership.MIXED_REFUSED,
    ),
    **_options("member-collaborative-events"),
    ("member-collaborative-event-register", "POST"): Refused(
        "collaborative registration can create a foreign-owned row",
        ownership=RowOwnership.MIXED_REFUSED,
    ),
    **_options("member-collaborative-event-register"),
    ("member-event-checkin-qr", "GET"): Refused(
        "event QR resolution can return foreign-owned registration rows",
        ownership=RowOwnership.MIXED_REFUSED,
    ),
    ("member-event-checkin-qr", "HEAD"): Refused(
        "event QR resolution can return foreign-owned registration rows",
        ownership=RowOwnership.MIXED_REFUSED,
    ),
    **_options("member-event-checkin-qr"),
}
