"""Atomic lifecycle transitions reserved for tenant import orchestration."""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.makerspaces.models import Makerspace


@transaction.atomic
def activate_imported_makerspace(makerspace_id: int) -> Makerspace:
    """Publish a fully materialized import as one locked state transition."""
    makerspace = Makerspace.objects.select_for_update().get(pk=makerspace_id)
    if makerspace.lifecycle_state != Makerspace.LifecycleState.IMPORTING:
        raise ValidationError("Only an importing makerspace can be activated.")
    makerspace.lifecycle_state = Makerspace.LifecycleState.ACTIVE
    makerspace.save(update_fields=["lifecycle_state", "updated_at"])
    return makerspace
