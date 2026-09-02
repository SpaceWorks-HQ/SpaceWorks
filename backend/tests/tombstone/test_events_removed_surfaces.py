"""apps/events under the tombstone profile (plan B5/B6, phase 13).

Events owns a module key, so the console tab drops itself and the relocation of the
staff API is the ordinary half of this phase. The half worth testing hard is retention:
events is the first separable app that holds **encrypted PII** and is a **payment
subject**, which is exactly the pair B1 says must stay registered while the surfaces go.

Both fail quietly if they regress. Deregistering `events.EventRegistration` from the PII
map does not raise -- `ScopedPiiModelMixin` reads an empty answer as "holds no PII" and
every protection no-ops in the safe-looking direction, which is the fail-OPEN B3 exists
to close. Dropping the purge plan is just as quiet: retained rows become unpurgeable and
their private objects unnameable. So the assertions here are that the tombstone took the
routes and nothing else.
"""

import pytest
from django.conf import settings
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from apps.events.models import Event, EventRegistration
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import module_available
from apps.makerspaces.platform import available_modules
from apps.operations.management.commands.run_scheduled_tasks import SCHEDULED_TASKS
from apps.separability.registry import pii_fields_for, purge_plan_for, runtime_active

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# Surfaces: gone.
# --------------------------------------------------------------------------

def test_the_app_is_registered_as_inactive():
    assert runtime_active("events") is False
    assert module_available("events") is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/makerspaces/1/events/",
        "/api/v1/admin/makerspaces/1/event-series/",
        "/api/v1/admin/events/1/",
        "/api/v1/admin/event-series/1/",
        "/api/v1/admin/event-series/1/occurrences/",
        "/api/v1/admin/event-series/1/extend/",
        "/api/v1/admin/event-series/1/collaborators/",
        "/api/v1/admin/makerspaces/1/event-series-collaborations/",
        "/api/v1/admin/events/1/publish/",
        "/api/v1/admin/events/1/cancel/",
        "/api/v1/admin/events/1/complete/",
        "/api/v1/admin/events/1/registrations/",
        "/api/v1/admin/event-registrations/1/mark-attended/",
    ],
)
def test_no_staff_event_route_resolves(path):
    with pytest.raises(Resolver404):
        resolve(path)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/public/demo/events/",
        "/api/v1/public/demo/events/0e2b1c94-1f5a-4a0b-8f2a-2f1d3c4b5a60/register/",
    ],
)
def test_no_public_event_route_resolves(path):
    """The member-facing half goes with the same tombstone as the staff half."""
    with pytest.raises(Resolver404):
        resolve(path)


def test_the_neighbours_sharing_both_prefixes_still_resolve():
    """Events straddled two shared prefixes; withdrawing it must not take a neighbour.

    The neighbours named here are ones no later phase withdraws: roles live in
    `admin_api` and `apps.machines` is the kernel. Naming bookings would pass today and
    start failing in phase 14 for a reason that has nothing to do with events.
    """
    assert resolve("/api/v1/admin/makerspaces/1/roles/1").url_name == "admin-role-detail"
    assert resolve("/api/v1/admin/machines/1/publicity").url_name == "admin-machine-publicity"
    assert resolve("/api/v1/public/demo/machines").url_name == "public-machines"


def test_the_openapi_schema_does_not_advertise_events():
    response = APIClient().get("/schema/?format=json")

    assert response.status_code == 200
    assert b"/events/" not in response.content
    assert b"/event-series/" not in response.content
    assert b"/event-registrations/" not in response.content


def test_the_series_extension_task_is_not_scheduled():
    task = "apps.events.tasks.extend_event_series_task"
    beat_tasks = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    runner_tasks = {dotted for _name, dotted, _minutes in SCHEDULED_TASKS}

    assert task not in beat_tasks
    assert task not in runner_tasks


def test_the_module_is_not_offered_to_the_console():
    space = Makerspace.objects.create(name="tombstoned-events", slug="tombstoned-events")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"events"})
    space.save(update_fields=["enabled_modules"])

    assert "events" not in available_modules(space)


# --------------------------------------------------------------------------
# Data and retention: untouched.
# --------------------------------------------------------------------------

def test_event_rows_are_still_readable():
    from tests.return_helpers import make_space
    from django.utils import timezone

    space = make_space("retained-events")
    event = Event.objects.create(
        makerspace=space,
        title="Soldering 101",
        starts_at=timezone.now(),
        ends_at=timezone.now() + timezone.timedelta(hours=2),
    )

    assert Event.objects.get(pk=event.pk).title == "Soldering 101"


def test_the_registration_pii_mapping_survives_the_tombstone():
    """The fail-OPEN case: an unmapped model stores plaintext and raises nothing."""
    fields = pii_fields_for("events.EventRegistration")

    assert fields, "EventRegistration must stay mapped or its PII silently goes plaintext"
    assert {field.field_name for field in fields} == {"name", "email", "phone"}


def test_the_purge_plan_is_still_registered():
    """Retention outlives the surfaces, or retained rows become unpurgeable."""
    plan = purge_plan_for("events")

    assert plan is not None
    assert "events.EventRegistration" in plan.pii_labels


def test_a_historic_event_registration_payment_is_still_nameable():
    """Payment rows are immutable and generic-keyed, so nothing cascades them.

    A charge taken before the tombstone outlives the surfaces that created it, and
    reconciliation still has to say what it was for. The label is resolved by importing
    the events model, which a tombstone deliberately leaves in place.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.payments.models import Payment
    from apps.payments.subjects import resolve_subject_labels, subject_label
    from tests.return_helpers import make_space, make_user

    space = make_space("retained-events-payment")
    event = Event.objects.create(
        makerspace=space,
        title="Laser cutter induction",
        starts_at=timezone.now(),
        ends_at=timezone.now() + timedelta(hours=1),
    )
    registration = EventRegistration.objects.create(
        event=event, name="Ada", email="ada@example.com", phone="",
    )
    payment = Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=registration.pk,
        amount="12.00",
        currency="eur",
        created_by=make_user("events-tombstone-cashier"),
    )

    # Asserted through `subject_label`, not the raw map -- see the twin in
    # `test_bookings_removed_surfaces.py`. The map entry now carries the owning
    # makerspace/member ids so a live lookup cannot hand one tenant's title to another.
    labels = resolve_subject_labels([payment])

    assert subject_label(payment, labels) == "Laser cutter induction"


def test_the_registration_model_is_still_a_scoped_pii_model():
    """The mapping above only protects anything while the mixin is still in play."""
    from apps.encryption.mappers import ScopedPiiModelMixin

    assert issubclass(EventRegistration, ScopedPiiModelMixin)
