"""Series-level organizer changes and their projection onto occurrences.

Before this module the superadmin console added and removed ``EventSeriesOrganizer`` rows
directly in ``admin.py`` and re-implemented the occurrence projection inline, so the admin
path skipped the module lock and the authority check that ``services_series`` applies when
it materializes a series. Superadmin operations must route through services, never through
the ORM (``docs/PROJECT-STATUS.md``); this is the service.
"""
from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.audit import services as audit
from apps.events.models_series import EventSeries, EventSeriesOrganizer
from apps.events.organizer_models import EventOrganizer
from apps.events.series_authority import can_manage_series
from apps.makerspaces.guards import require_module_locked


def project_organizer(source, events):
    """Create the per-occurrence organizer rows a series organizer implies."""
    for event in events:
        EventOrganizer.objects.get_or_create(
            event=event,
            organization=source.organization,
            defaults={"created_by": source.created_by, "source_series_organizer": source},
        )


def _lock(series):
    locked = EventSeries.objects.select_for_update().get(pk=series.pk)
    require_module_locked(locked.makerspace_id, "events")
    return locked


def _meta(series, organization):
    return {"series_id": series.pk, "organization_slug": organization.slug}


@transaction.atomic
def add_series_organizer(series, *, actor, organization):
    locked = _lock(series)
    if not can_manage_series(actor, locked):
        raise PermissionDenied()
    row, created = EventSeriesOrganizer.objects.get_or_create(
        series=locked, organization=organization, defaults={"created_by": actor}
    )
    project_organizer(row, locked.occurrences.all())
    audit.record(
        actor,
        "event.series_organizer_created" if created else "event.series_organizer_updated",
        makerspace=locked.makerspace,
        target=row,
        meta=_meta(locked, organization),
    )
    return row


@transaction.atomic
def remove_series_organizer(row, *, actor):
    locked = _lock(row.series)
    if not can_manage_series(actor, locked):
        raise PermissionDenied()
    organization = row.organization
    EventOrganizer.objects.filter(source_series_organizer=row).delete()
    audit.record(
        actor,
        "event.series_organizer_deleted",
        makerspace=locked.makerspace,
        target=row,
        meta=_meta(locked, organization),
    )
    row.delete()
