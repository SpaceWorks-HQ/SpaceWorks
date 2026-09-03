from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from threading import Barrier
from types import SimpleNamespace

import pytest
from django.urls import reverse
from django.db import close_old_connections
from django.utils import timezone
from rest_framework import serializers
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.events import services, services_series, services_series_lifecycle
from apps.events.models import Event, EventSeries
from apps.events.services_recurrence import occurrences, validate_series_recurrence
from apps.events.tasks import extend_published_series
from apps.makerspaces.models import (
    DEFAULT_ENABLED_MODULES,
    Makerspace,
    MakerspaceMembership,
)

pytestmark = pytest.mark.django_db


def make_space(slug, *, events=True):
    modules = set(DEFAULT_ENABLED_MODULES)
    if events:
        modules.add("events")
    else:
        modules.discard("events")
    return Makerspace.objects.create(
        name=slug, slug=slug, enabled_modules=sorted(modules)
    )


def make_manager(space, username="series-manager"):
    actor = User.objects.create_user(username=username)
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return actor


def recurrence_fixture(**overrides):
    values = {
        "recurrence_timezone": "America/New_York",
        "dtstart_local_date": date(2026, 3, 1),
        "dtstart_local_time": time(18),
        "recurrence_rule": "FREQ=WEEKLY;COUNT=4",
        "duration_minutes": 60,
        "revision": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def create_daily_series(space, actor, *, title="Open studio"):
    tomorrow = (timezone.now() + timedelta(days=1)).date()
    series, created = services_series.create_series(
        makerspace=space,
        actor=actor,
        title=title,
        recurrence_timezone="UTC",
        dtstart_local_date=tomorrow,
        dtstart_local_time=time(10),
        recurrence_rule="FREQ=DAILY",
        duration_minutes=60,
    )
    return series, created


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_weekly_occurrences_keep_local_wall_time_across_dst():
    expanded = occurrences(
        recurrence_fixture(),
        now=datetime(2026, 2, 28, tzinfo=dt_timezone.utc),
    )

    assert [row.local_start.hour for row in expanded] == [18, 18, 18, 18]
    assert [row.starts_at.hour for row in expanded] == [23, 22, 22, 22]


def test_nonexistent_spring_forward_wall_time_is_skipped():
    expanded = occurrences(
        recurrence_fixture(
            dtstart_local_time=time(2, 30),
            recurrence_rule="FREQ=WEEKLY;COUNT=3",
        ),
        now=datetime(2026, 2, 28, tzinfo=dt_timezone.utc),
    )

    assert [row.local_start.day for row in expanded] == [1, 15]


def test_autumn_dst_and_half_hour_zone_keep_the_wall_clock_anchor():
    autumn = occurrences(
        recurrence_fixture(
            dtstart_local_date=date(2026, 10, 25),
            recurrence_rule="FREQ=WEEKLY;COUNT=4",
        ),
        now=datetime(2026, 10, 24, tzinfo=dt_timezone.utc),
    )
    india = occurrences(
        recurrence_fixture(
            recurrence_timezone="Asia/Kolkata",
            dtstart_local_time=time(18, 30),
        ),
        now=datetime(2026, 2, 28, tzinfo=dt_timezone.utc),
    )

    assert [row.local_start.hour for row in autumn] == [18, 18, 18, 18]
    assert [row.starts_at.hour for row in autumn] == [22, 23, 23, 23]
    assert {(row.local_start.hour, row.local_start.minute) for row in india} == {(18, 30)}


def test_recurrence_too_dense_for_hourly_extension_is_rejected():
    with pytest.raises(serializers.ValidationError) as caught:
        validate_series_recurrence(
            recurrence_fixture(recurrence_rule="FREQ=MINUTELY")
        )

    assert caught.value.get_codes() == {"recurrence_rule": "recurrence_too_dense"}


def test_manual_extension_refills_the_bounded_window_idempotently(monkeypatch):
    space = make_space("series-extension")
    actor = make_manager(space)
    series, initial = create_daily_series(space, actor)
    assert len(initial) == 48

    advanced = timezone.now() + timedelta(days=30)
    monkeypatch.setattr(services_series.timezone, "now", lambda: advanced)
    _series, added = services_series.extend_series(series, actor=actor)
    _series, repeated = services_series.extend_series(series, actor=actor)

    assert len(added) > 0
    assert repeated == []
    assert Event.objects.filter(series=series).count() == len(initial) + len(added)
    assert AuditLog.objects.filter(action="event.series_extended").count() == 2


def test_occurrence_override_survives_template_update_and_can_be_reset():
    space = make_space("series-overrides")
    actor = make_manager(space)
    series, created = create_daily_series(space, actor)
    occurrence = created[0]

    services.update_event(occurrence, actor=actor, title="Special session")
    services_series.update_series(
        series, actor=actor, title="New default", description="Shared description"
    )
    occurrence.refresh_from_db()
    assert occurrence.title == "Special session"
    assert occurrence.description == "Shared description"
    assert occurrence.series_override_fields == ["title"]

    services.update_event(occurrence, actor=actor, inherit_fields=["title"])
    occurrence.refresh_from_db()
    assert occurrence.title == "New default"
    assert occurrence.series_override_fields == []


def test_series_create_api_has_positive_and_module_off_sides():
    enabled = make_space("series-api-on")
    disabled = make_space("series-api-off", events=False)
    actor = make_manager(enabled, "series-api-manager")
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=disabled,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    tomorrow = (timezone.now() + timedelta(days=1)).date().isoformat()
    payload = {
        "title": "Weekly class",
        "recurrence_timezone": "Asia/Kolkata",
        "dtstart_local_date": tomorrow,
        "dtstart_local_time": "18:30:00",
        "recurrence_rule": "FREQ=WEEKLY",
        "duration_minutes": 90,
    }

    created = client_for(actor).post(
        reverse("admin-event-series-list-create", kwargs={"makerspace_id": enabled.pk}),
        payload,
        format="json",
    )
    blocked = client_for(actor).post(
        reverse("admin-event-series-list-create", kwargs={"makerspace_id": disabled.pk}),
        payload,
        format="json",
    )
    invalid = client_for(actor).post(
        reverse("admin-event-series-list-create", kwargs={"makerspace_id": enabled.pk}),
        {**payload, "recurrence_timezone": "Mars/Olympus_Mons"},
        format="json",
    )

    assert created.status_code == 201
    assert created.data["affected_count"] == 48
    assert blocked.status_code == 400
    assert invalid.status_code == 400
    assert EventSeries.objects.filter(makerspace=enabled).count() == 1
    assert not EventSeries.objects.filter(makerspace=disabled).exists()


def test_scheduled_extension_runs_for_enabled_series_and_skips_module_off(monkeypatch):
    enabled, disabled = make_space("series-task-on"), make_space("series-task-off")
    actor = make_manager(enabled, "series-task-manager")
    enabled_series, enabled_initial = create_daily_series(enabled, actor, title="Enabled")
    disabled_series, disabled_initial = create_daily_series(disabled, actor, title="Disabled")
    EventSeries.objects.filter(pk__in=[enabled_series.pk, disabled_series.pk]).update(
        status=EventSeries.Status.PUBLISHED
    )
    disabled.enabled_modules = [key for key in disabled.enabled_modules if key != "events"]
    disabled.save(update_fields=["enabled_modules"])
    advanced = timezone.now() + timedelta(days=30)
    monkeypatch.setattr("apps.events.tasks.timezone.now", lambda: advanced)

    extend_published_series()

    assert Event.objects.filter(series=enabled_series).count() > len(enabled_initial)
    assert Event.objects.filter(series=disabled_series).count() == len(disabled_initial)


def test_series_cancellation_suppresses_occurrence_notification_fanout(monkeypatch):
    space = make_space("series-notifications")
    actor = make_manager(space)
    series, created = create_daily_series(space, actor)
    series.status = EventSeries.Status.PUBLISHED
    series.save(update_fields=["status"])
    Event.objects.filter(pk__in=[row.pk for row in created]).update(
        status=Event.Status.PUBLISHED
    )
    event_notifications = []
    series_notifications = []
    monkeypatch.setattr(
        services, "notify_event_lifecycle", lambda *args: event_notifications.append(args)
    )
    monkeypatch.setattr(
        services_series_lifecycle,
        "notify_series_lifecycle",
        lambda *args: series_notifications.append(args),
    )

    services_series.cancel_series(series, actor=actor)

    assert event_notifications == []
    assert len(series_notifications) == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_extensions_materialize_each_occurrence_once(monkeypatch):
    space = make_space("series-concurrent-extension")
    actor = make_manager(space, "series-concurrent-manager")
    series, initial = create_daily_series(space, actor)
    advanced = timezone.now() + timedelta(days=30)
    monkeypatch.setattr(services_series.timezone, "now", lambda: advanced)
    barrier = Barrier(2)

    def extend():
        close_old_connections()
        try:
            barrier.wait()
            _series, created = services_series.extend_series(
                EventSeries.objects.get(pk=series.pk),
                actor=User.objects.get(pk=actor.pk),
            )
            return len(created)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(pool.map(lambda _index: extend(), range(2)))

    keys = Event.objects.filter(series=series).values_list("series_occurrence_key", flat=True)
    assert min(counts) == 0 < max(counts)
    assert len(keys) == len(set(keys))
    assert len(keys) == len(initial) + sum(counts)
