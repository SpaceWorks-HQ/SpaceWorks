"""Public catalogue scope after a caller resolves a servable tenant and module gates."""

from apps.makerspaces.servability import is_servable


def scope_public_catalogue(queryset, makerspace, field="makerspace_id"):
    # Hiding a space from global administrators is not hiding its public catalogue.
    # This helper admits public tenant data only; callers still allowlist item fields.
    if not makerspace.public_inventory_enabled:
        return queryset.none()
    return scope_verified_tenant(queryset, makerspace, field)


def scope_verified_tenant(queryset, makerspace, field="makerspace_id"):
    """Pin a domain read to a tenant already authorized by its view or workflow.

    This is not an actor authorization entry point. It prevents an internal
    catalogue/meter read from borrowing scheduled-work's global-admin hide rule.
    """
    if type(makerspace) is int:
        from apps.makerspaces.models import Makerspace
        from apps.makerspaces.servability import servable_queryset
        tenants = servable_queryset(Makerspace.objects.filter(pk=makerspace)).values("pk")
        return queryset.filter(**{f"{field}__in": tenants})
    if not is_servable(makerspace):
        return queryset.none()
    return queryset.filter(**{field: makerspace.pk})
