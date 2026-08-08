"""apps/notifications under the tombstone profile (plan B5/B6, phase 9).

The interesting property here is not the URLs -- it is that a dozen unrelated
workflows write notifications, and none of them needed to learn about tombstones.
`emit_notification` already asked `module_enabled`, which now ANDs in
`module_available`, so hardware requests, machine service, bookings and dispatch all
stop emitting through one gate. The test below exercises that from a real workflow
rather than by calling the gate directly.
"""

import pytest
from django.contrib import admin
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import module_available
from apps.makerspaces.platform import available_modules
from apps.notifications.emit import emit_notification
from apps.notifications.models import Notification
from apps.separability.registry import purge_plan_for, runtime_active

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# Surfaces: gone.
# --------------------------------------------------------------------------

def test_the_app_is_registered_as_inactive():
    assert runtime_active("notifications") is False
    assert module_available("notifications") is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/notifications/makerspace/1",
        "/api/v1/notifications/makerspace/1/unread-count",
        "/api/v1/notifications/makerspace/1/read-all",
        "/api/v1/notifications/makerspace/1/2/read",
    ],
)
def test_no_notification_route_resolves(path):
    with pytest.raises(Resolver404):
        resolve(path)


def test_the_inbox_endpoint_returns_404():
    assert APIClient().get("/api/v1/notifications/makerspace/1").status_code == 404


def test_the_admin_does_not_register_the_model():
    assert Notification not in admin.site._registry


def test_the_openapi_schema_does_not_advertise_notifications():
    response = APIClient().get("/schema/?format=json")

    assert response.status_code == 200
    assert b"/api/v1/notifications/" not in response.content


def test_the_module_is_not_offered_to_the_console():
    space = Makerspace.objects.create(name="tombstoned-notify", slug="tombstoned-notify")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"notifications"})
    space.save(update_fields=["enabled_modules"])

    assert "notifications" not in available_modules(space)


# --------------------------------------------------------------------------
# The chokepoint: every emitter stops without knowing why.
# --------------------------------------------------------------------------

def test_emitting_is_a_no_op_even_for_a_makerspace_that_enabled_the_module():
    space = Makerspace.objects.create(name="emit-off", slug="emit-off")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"notifications"})
    space.save(update_fields=["enabled_modules"])

    emit_notification(space, title="Request submitted", event="request.submitted")

    assert not Notification.objects.exists()


def test_a_real_workflow_completes_without_its_notification():
    """Emitting is fail-safe by design, so a tombstone must not break the workflow."""
    from tests.return_helpers import make_space, make_user

    space = make_space("tombstone-emit-workflow")
    actor = make_user("tombstone-emit-actor")

    emit_notification(space, title="Anything", event="anything", body="x", url_path="/admin")

    assert not Notification.objects.exists()
    assert actor.pk is not None


# --------------------------------------------------------------------------
# Data and retention: untouched.
# --------------------------------------------------------------------------

def test_existing_notification_rows_are_still_readable():
    space = Makerspace.objects.create(name="retained-notify", slug="retained-notify")
    row = Notification.objects.create(makerspace=space, title="Old", event="legacy")

    assert Notification.objects.get(pk=row.pk).title == "Old"


def test_the_purge_plan_is_still_registered():
    assert purge_plan_for("notifications") is not None
