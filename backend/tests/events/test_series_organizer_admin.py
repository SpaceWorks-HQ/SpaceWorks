"""The superadmin series-organizer admin must route through the series service.

Before phase 0 the admin wrote ``EventOrganizer`` rows directly, skipping the events module
lock, the series row lock and the authority check the service applies.
"""
from datetime import time, timedelta

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.events import services_series, services_series_organizers
from apps.events.admin import EventSeriesOrganizerAdmin
from apps.events.models import EventOrganizer, EventSeriesOrganizer
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.organizations.models import Organization
from tests.module_helpers import disable_module

pytestmark = pytest.mark.django_db


def _space():
    return Makerspace.objects.create(name="Series Space", slug="series-space")


def _manager(space):
    user = User.objects.create_user(
        username="series-manager", role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user, makerspace=space, role=MakerspaceMembership.Role.SPACE_MANAGER
    )
    return user


def _superadmin():
    return User.objects.create_user(
        username="root", role=User.Role.SUPERADMIN, is_superuser=True, is_staff=True,
        access_status=User.AccessStatus.ACTIVE,
    )


def _series(space, actor):
    series, _occurrences = services_series.create_series(
        makerspace=space, actor=actor, title="Weekly build night",
        recurrence_timezone="UTC",
        dtstart_local_date=(timezone.now() + timedelta(days=1)).date(),
        dtstart_local_time=time(18), recurrence_rule="FREQ=DAILY", duration_minutes=90,
    )
    return series


def _admin_request(user):
    request = RequestFactory().post("/control/events/eventseriesorganizer/add/")
    request.user = user
    return request


def test_admin_add_projects_to_every_occurrence_through_the_service():
    space = _space()
    series = _series(space, _manager(space))
    org = Organization.objects.create(name="Partner Org", slug="partner-org")
    root = _superadmin()
    admin = EventSeriesOrganizerAdmin(EventSeriesOrganizer, AdminSite())
    unsaved = EventSeriesOrganizer(series=series, organization=org)

    admin.save_model(_admin_request(root), unsaved, form=None, change=False)

    row = EventSeriesOrganizer.objects.get(series=series, organization=org)
    assert row.created_by == root
    occurrences = list(series.occurrences.all())
    assert occurrences, "create_series materializes at least one occurrence"
    projected = EventOrganizer.objects.filter(source_series_organizer=row)
    assert projected.count() == len(occurrences)
    assert set(projected.values_list("event_id", flat=True)) == {e.pk for e in occurrences}
    log = AuditLog.objects.get(action="event.series_organizer_created")
    assert log.actor == root and log.makerspace == space
    assert log.meta["series_id"] == series.pk
    assert log.meta["organization_slug"] == "partner-org"


def test_admin_delete_removes_projection_and_audits():
    space = _space()
    series = _series(space, _manager(space))
    org = Organization.objects.create(name="Partner Org", slug="partner-org")
    root = _superadmin()
    row = services_series_organizers.add_series_organizer(series, actor=root, organization=org)
    assert EventOrganizer.objects.filter(source_series_organizer=row).exists()

    admin = EventSeriesOrganizerAdmin(EventSeriesOrganizer, AdminSite())
    admin.delete_model(_admin_request(root), row)

    assert not EventSeriesOrganizer.objects.filter(pk=row.pk).exists()
    assert not EventOrganizer.objects.filter(organization=org).exists()
    assert AuditLog.objects.filter(action="event.series_organizer_deleted").count() == 1


def test_service_refuses_when_the_events_module_is_off():
    space = _space()
    manager = _manager(space)
    series = _series(space, manager)
    org = Organization.objects.create(name="Partner Org", slug="partner-org")
    disable_module(space, "events")
    with pytest.raises(ValidationError):
        services_series_organizers.add_series_organizer(series, actor=_superadmin(), organization=org)
    assert not EventSeriesOrganizer.objects.exists()


def test_service_refuses_an_actor_without_series_authority():
    space = _space()
    series = _series(space, _manager(space))
    org = Organization.objects.create(name="Partner Org", slug="partner-org")
    outsider = User.objects.create_user(
        username="outsider", role=User.Role.REQUESTER, access_status=User.AccessStatus.ACTIVE
    )
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        services_series_organizers.add_series_organizer(series, actor=outsider, organization=org)


def test_admin_no_longer_touches_organizer_rows_directly():
    import inspect

    from apps.events import admin as events_admin

    source = inspect.getsource(events_admin.EventSeriesOrganizerAdmin)
    assert "EventOrganizer.objects" not in source
    assert "audit.record" not in source
