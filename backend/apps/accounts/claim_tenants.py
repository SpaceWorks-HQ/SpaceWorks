"""Strictly single-tenant resolution for claim-route policies."""

from django.apps import apps

from apps.accounts.claim_route_types import (
    BODY_OBJECT,
    ID,
    PUBLIC_TOKEN,
    SLUG,
)
from apps.makerspaces.servability import is_servable, servable_queryset


class ClaimTenantResolutionError(ValueError):
    pass


PUBLIC_TOKEN_TARGETS = {
    "public-booking-submit": ("bookings.BookableSpace", "public_token"),
    # Present for completeness even though the matrix refuses registration: changing
    # that disposition later must still resolve the exact event row, never trust slug.
    "public-event-register": ("events.Event", "public_token"),
}
BODY_OBJECT_TARGETS = {
    "public-machine-service-request-submit": ("machines.Machine", "machine_id"),
}


def resolve_claim_tenant(resolver, *, view_name, url_kwargs, body=None):
    """Resolve the row-owning Makerspace named by one matrix resolver.

    Missing, malformed, or unrecognised inputs fail closed. This function deliberately
    knows nothing about collaborations or ``Payment.via_makerspace``: a claim is bound
    to one owning tenant, not to a graph of spaces an ordinary account can traverse.
    """
    from apps.makerspaces.models import Makerspace

    if resolver == SLUG:
        tenant = servable_queryset(Makerspace.objects.filter(
            slug=url_kwargs.get("makerspace_slug")
        )).first()
    elif resolver == ID:
        tenant = servable_queryset(Makerspace.objects.filter(
            pk=_positive_int(url_kwargs.get("makerspace_id"))
        )).first()
    elif resolver == PUBLIC_TOKEN:
        tenant = _object_tenant(
            PUBLIC_TOKEN_TARGETS, view_name, url_kwargs, body or {}
        )
    elif resolver == BODY_OBJECT:
        tenant = _object_tenant(
            BODY_OBJECT_TARGETS, view_name, url_kwargs, body or {}
        )
    else:
        raise ClaimTenantResolutionError(f"Unknown claim tenant resolver: {resolver!r}")
    slug = url_kwargs.get("makerspace_slug")
    if tenant is not None and slug is not None and tenant.slug != slug:
        raise ClaimTenantResolutionError("URL and object tenants do not match.")
    if tenant is None or not is_servable(tenant):
        raise ClaimTenantResolutionError("Claim route tenant could not be resolved.")
    return tenant


def claim_tenant_matches(
    resolver, *, claim_makerspace_id, view_name, url_kwargs, body=None
):
    try:
        tenant = resolve_claim_tenant(
            resolver,
            view_name=view_name,
            url_kwargs=url_kwargs,
            body=body,
        )
    except ClaimTenantResolutionError:
        return False
    return tenant.pk == claim_makerspace_id


def _object_tenant(targets, view_name, url_kwargs, body):
    try:
        model_label, lookup_field = targets[view_name]
    except KeyError as exc:
        raise ClaimTenantResolutionError(
            f"No object tenant mapping for {view_name}."
        ) from exc
    raw_value = url_kwargs.get(lookup_field)
    if raw_value is None:
        raw_value = body.get(lookup_field)
    if raw_value in (None, ""):
        raise ClaimTenantResolutionError("Claim route object identifier is missing.")
    model = apps.get_model(model_label)
    row = model.objects.select_related("makerspace").filter(
        **{lookup_field if lookup_field == "public_token" else "pk": raw_value}
    ).first()
    return None if row is None else row.makerspace


def _positive_int(value):
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ClaimTenantResolutionError("Invalid makerspace id.") from exc
    if value <= 0:
        raise ClaimTenantResolutionError("Invalid makerspace id.")
    return value
