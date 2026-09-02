from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from apps.audit import services as audit
from apps.events.models import Event, EventCollaborator, EventSeries, EventSeriesCollaborator
from apps.makerspaces.guards import require_module_locked
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset


def _rows(series):
    return series.collaborators.select_related("makerspace").order_by("makerspace__slug", "pk")


def _lock_spaces(space_ids):
    expected = set(space_ids)
    spaces = list(Makerspace.objects.select_for_update().filter(
        pk__in=expected
    ).order_by("pk"))
    if {space.pk for space in spaces} != expected:
        raise NotFound("A series makerspace no longer exists.")
    for space in spaces:
        require_module_locked(space, "events")
    return {space.pk: space for space in spaces}


def _project(source):
    if source.status != EventSeriesCollaborator.Status.ACCEPTED:
        return
    for event in Event.objects.filter(
        series=source.series,
        ends_at__gte=timezone.now(),
    ).order_by("pk"):
        EventCollaborator.objects.update_or_create(
            event=event,
            makerspace=source.makerspace,
            defaults={
                "status": EventCollaborator.Status.ACCEPTED,
                "invited_by": source.invited_by,
                "responded_by": source.responded_by,
                "responded_at": source.responded_at,
                "source_series_collaboration": source,
            },
        )


@transaction.atomic
def invite_collaborators(series, *, actor, slugs):
    locked = EventSeries.objects.select_for_update().get(pk=series.pk)
    normalized = sorted({str(slug).strip().lower() for slug in slugs if str(slug).strip()})
    spaces = list(servable_queryset(
        Makerspace.objects.filter(slug__in=normalized), relation=None
    ).order_by("pk"))
    by_slug = {space.slug: space for space in spaces}
    invalid = sorted(set(normalized) - set(by_slug))
    if locked.makerspace.slug in normalized:
        invalid.append(locked.makerspace.slug)
    if invalid:
        raise serializers.ValidationError({"slugs": f"Unknown or host slug(s): {', '.join(invalid)}."})
    _lock_spaces({locked.makerspace_id, *(space.pk for space in spaces)})
    requested_ids = {space.pk for space in spaces}
    removed = list(EventSeriesCollaborator.objects.filter(series=locked).exclude(
        makerspace_id__in=requested_ids
    ).values_list("pk", flat=True))
    if removed:
        EventCollaborator.objects.filter(source_series_collaboration_id__in=removed).delete()
        EventSeriesCollaborator.objects.filter(pk__in=removed).delete()
    existing = {row.makerspace_id: row for row in locked.collaborators.all()}
    for space in spaces:
        if space.pk not in existing:
            EventSeriesCollaborator.objects.create(
                series=locked, makerspace=space, invited_by=actor
            )
    audit.record(
        actor, "event.series_collaborators_changed", makerspace=locked.makerspace,
        target=locked, meta={"slugs": normalized},
    )
    return _rows(locked)


@transaction.atomic
def remove_collaborator(collaborator_id, *, actor):
    series_id = EventSeriesCollaborator.objects.filter(pk=collaborator_id).values_list(
        "series_id", flat=True
    ).first()
    if series_id is None:
        raise NotFound("This series collaboration no longer exists.")
    series = EventSeries.objects.select_for_update().get(pk=series_id)
    collaborator_space_id = EventSeriesCollaborator.objects.filter(
        pk=collaborator_id, series=series
    ).values_list("makerspace_id", flat=True).first()
    if collaborator_space_id is None:
        raise NotFound("This series collaboration no longer exists.")
    _lock_spaces((series.makerspace_id, collaborator_space_id))
    row = EventSeriesCollaborator.objects.select_for_update().filter(
        pk=collaborator_id, series=series
    ).first()
    if row is None:
        raise NotFound("This series collaboration no longer exists.")
    slug = row.makerspace.slug
    EventCollaborator.objects.filter(source_series_collaboration=row).delete()
    row.delete()
    audit.record(
        actor, "event.series_collaborators_changed", makerspace=series.makerspace,
        target=series, meta={"removed": slug},
    )


@transaction.atomic
def respond(collaborator, *, actor, accept):
    series = EventSeries.objects.select_for_update().get(pk=collaborator.series_id)
    spaces = _lock_spaces((series.makerspace_id, collaborator.makerspace_id))
    space = spaces[collaborator.makerspace_id]
    row = EventSeriesCollaborator.objects.select_for_update().filter(
        pk=collaborator.pk, series=series
    ).first()
    if row is None:
        raise NotFound("This series collaboration invitation no longer exists.")
    row.status = (
        EventSeriesCollaborator.Status.ACCEPTED
        if accept else EventSeriesCollaborator.Status.DECLINED
    )
    row.responded_by = actor
    row.responded_at = timezone.now()
    row.save(update_fields=("status", "responded_by", "responded_at"))
    if accept:
        _project(row)
    else:
        EventCollaborator.objects.filter(source_series_collaboration=row).delete()
    audit.record(
        actor,
        "event.series_collaboration_accepted" if accept else "event.series_collaboration_declined",
        makerspace=space, target=row, meta={"series_id": series.pk},
    )
    return row
