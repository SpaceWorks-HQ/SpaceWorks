import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.events.models import EventSeries
from apps.events.services_series import _materialize_locked
from apps.events.notifications import notify_series_lifecycle
from apps.makerspaces.guards import require_module_locked
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset


logger = logging.getLogger(__name__)


def extend_published_series():
    series_ids = servable_queryset(
        EventSeries.objects.filter(
            status=EventSeries.Status.PUBLISHED,
            makerspace__enabled_modules__contains=["events"],
        ),
        relation="makerspace",
    ).order_by("pk").values_list("pk", flat=True)
    for series_id in series_ids.iterator(chunk_size=100):
        try:
            with transaction.atomic():
                series = EventSeries.objects.select_for_update().get(pk=series_id)
                locked_space = Makerspace.objects.select_for_update().get(
                    pk=series.makerspace_id
                )
                require_module_locked(locked_space, "events")
                series.makerspace = locked_space
                created = _materialize_locked(series, actor=None, now=timezone.now())
                if created:
                    audit.record(
                        None, "event.series_extended", makerspace=series.makerspace,
                        target=series, meta={"created_ids": [row.pk for row in created]},
                    )
        except Exception as exc:  # noqa: BLE001 - one bad legacy rule must not stop others
            code = getattr(exc, "default_code", exc.__class__.__name__)
            code = str(code)[:64]
            logger.exception("event series extension failed", extra={"series_id": series_id})
            with transaction.atomic():
                series = EventSeries.objects.select_for_update().filter(pk=series_id).first()
                if series is None:
                    continue
                series.last_generation_error_code = code
                series.save(update_fields=("last_generation_error_code", "updated_at"))
                audit.record(
                    None, "event.series_generation_failed", makerspace=series.makerspace,
                    target=series, meta={"error_code": code},
                )
                notify_series_lifecycle(series, "series_generation_failed")


@shared_task
def extend_event_series_task():
    extend_published_series()
