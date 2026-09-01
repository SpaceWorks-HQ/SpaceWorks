from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.events import services
from apps.events.exceptions import EventInvalidTransition
from apps.events.models import Event, EventSeries
from apps.events.notifications import notify_series_lifecycle
from apps.events.services_recurrence import recurrence_exhausted
from apps.makerspaces import limits
from apps.makerspaces.guards import require_module_locked


@transaction.atomic
def publish_series(series, *, actor):
    from apps.events.services_series import _materialize_locked, _validate

    locked = EventSeries.objects.select_for_update().get(pk=series.pk)
    if locked.status != EventSeries.Status.DRAFT:
        raise EventInvalidTransition("Only draft series can be published.")
    _validate(locked)
    list(Event.objects.select_for_update().filter(series=locked).order_by("pk"))
    require_module_locked(locked.makerspace_id, "events")
    _materialize_locked(locked, actor=actor, now=timezone.now())
    events = list(Event.objects.filter(
        series=locked, status=Event.Status.DRAFT, ends_at__gte=timezone.now()
    ).order_by("pk"))
    limits.check_quota(locked.makerspace, "events", adding=len(events))
    Event.objects.filter(pk__in=[event.pk for event in events]).update(
        status=Event.Status.PUBLISHED
    )
    locked.status = EventSeries.Status.PUBLISHED
    locked.save(update_fields=("status", "updated_at"))
    audit.record(
        actor, "event.series_published", makerspace=locked.makerspace, target=locked,
        meta={"published_count": len(events)},
    )
    notify_series_lifecycle(locked, "series_published")
    return locked, len(events)


@transaction.atomic
def cancel_series(series, *, actor):
    locked = EventSeries.objects.select_for_update().get(pk=series.pk)
    if locked.status != EventSeries.Status.PUBLISHED:
        raise EventInvalidTransition("Only a published series can be cancelled.")
    events = list(Event.objects.select_for_update().filter(
        series=locked, status=Event.Status.PUBLISHED, ends_at__gte=timezone.now()
    ).order_by("pk"))
    require_module_locked(locked.makerspace_id, "events")
    for event in events:
        services.cancel(event, actor=actor, notify=False)
    locked.status = EventSeries.Status.CANCELLED
    locked.save(update_fields=("status", "updated_at"))
    audit.record(
        actor, "event.series_cancelled", makerspace=locked.makerspace, target=locked,
        meta={"cancelled_count": len(events)},
    )
    notify_series_lifecycle(locked, "series_cancelled")
    return locked, len(events)


@transaction.atomic
def complete_series(series, *, actor):
    locked = EventSeries.objects.select_for_update().get(pk=series.pk)
    if locked.status != EventSeries.Status.PUBLISHED:
        raise EventInvalidTransition("Only a published series can be completed.")
    events = list(Event.objects.select_for_update().filter(series=locked).order_by("pk"))
    require_module_locked(locked.makerspace_id, "events")
    if not recurrence_exhausted(locked, now=timezone.now()):
        raise EventInvalidTransition("The recurrence is unbounded or not yet exhausted.")
    if any(event.status == Event.Status.PUBLISHED for event in events):
        raise EventInvalidTransition("Complete or cancel every occurrence first.")
    locked.status = EventSeries.Status.COMPLETED
    locked.save(update_fields=("status", "updated_at"))
    audit.record(actor, "event.series_completed", makerspace=locked.makerspace, target=locked)
    notify_series_lifecycle(locked, "series_completed")
    return locked
