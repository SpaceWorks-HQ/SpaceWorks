"""Transaction-safe module disable guard (plan A8).

The boundary `require_module` reads an unlocked row, so on its own it loses a race
against a concurrent uninstall. The creation services take the same makerspace row
lock `module_install` takes, which serializes creators against disablers.
"""

import threading

import pytest
from django.db import connection, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import BookableSpace
from apps.bookings.services_bookings import create_booking
from apps.events import services as event_services
from apps.makerspaces.guards import require_module_locked
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_install import install_module, uninstall_module
from rest_framework.exceptions import ValidationError

pytestmark = pytest.mark.django_db(transaction=True)


def space(slug, *modules):
    item = Makerspace.objects.create(name=slug.title(), slug=slug)
    for key in modules:
        install_module(item, key)
    item.refresh_from_db()
    return item


def staff(name):
    return User.objects.create_user(username=name, email=f"{name}@example.test", password="password")


def test_creation_services_reject_a_module_disabled_after_the_boundary_check():
    # Simulates the exact race: the view-level gate passed, then the module was
    # uninstalled before the service ran.
    makerspace = space("race-events", "events")
    actor = staff("race-actor")
    uninstall_module(makerspace, "events")

    with pytest.raises(ValidationError) as exc:
        event_services.create_event(
            makerspace=makerspace, actor=actor, title="Late", description="",
            starts_at=timezone.now() + timezone.timedelta(days=1),
            ends_at=timezone.now() + timezone.timedelta(days=1, hours=2),
            location="Lab", capacity=0, is_public=True,
        )
    assert "module" in exc.value.detail


def test_booking_creation_rejects_a_disabled_module():
    makerspace = space("race-bookings", "bookings")
    bookable = BookableSpace.objects.create(makerspace=makerspace, name="Bench")
    uninstall_module(makerspace, "bookings")

    with pytest.raises(ValidationError) as exc:
        create_booking(
            bookable,
            starts_at=timezone.now() + timezone.timedelta(days=1),
            ends_at=timezone.now() + timezone.timedelta(days=1, hours=1),
            name="Someone", email="someone@example.test", phone="+10000000000",
        )
    assert "module" in exc.value.detail


def test_guard_blocks_until_a_concurrent_uninstall_commits():
    """The guard must actually take the row lock, not just re-read the row.

    A second connection holds the makerspace lock and uninstalls; the guard must
    wait for that commit and then observe the module as gone. If it read without
    locking it would see the pre-uninstall value and let the create through.
    """
    makerspace = space("race-lock", "events")
    holder_committed = threading.Event()
    guard_result = {}

    def uninstall_holding_the_lock():
        try:
            with transaction.atomic():
                # module_install takes select_for_update on the makerspace row.
                uninstall_module(makerspace, "events")
                # Hold the lock long enough that the guard must block on it.
                holder_committed.wait(timeout=5)
        finally:
            connection.close()

    holder = threading.Thread(target=uninstall_holding_the_lock)
    holder.start()

    def run_guard():
        try:
            with transaction.atomic():
                require_module_locked(makerspace, "events")
            guard_result["outcome"] = "allowed"
        except ValidationError:
            guard_result["outcome"] = "blocked"
        finally:
            connection.close()

    guard = threading.Thread(target=run_guard)
    # Give the holder time to take the lock before the guard tries.
    import time

    time.sleep(0.5)
    guard.start()
    holder_committed.set()
    holder.join(timeout=10)
    guard.join(timeout=10)

    assert guard_result.get("outcome") == "blocked"


def test_machine_creation_still_succeeds_with_the_locked_guard_in_place():
    # Machine create is the one guarded path that runs in a view rather than a
    # service, so the added row lock sits next to `check_quota` in the same atomic
    # block. The race itself is unobservable from the outside (the boundary check
    # rejects first), but breaking the happy path would be very observable.
    from django.urls import reverse

    from apps.machines.models import Machine, MachineType
    from tests.return_helpers import authenticated_client, make_member

    makerspace = space("race-machine-create", "machines")
    manager = make_member("race-machine-manager", makerspace)
    # A per-space custom type, not the seeded global one: these tests run with
    # `transaction=True`, which truncates the migration-seeded rows.
    machine_type = MachineType.objects.create(
        makerspace=makerspace, slug="laser", name="Laser Cutter"
    )

    response = authenticated_client(manager).post(
        reverse("admin-machines", kwargs={"makerspace_id": makerspace.id}),
        {"machine_type_id": machine_type.id, "name": "Workshop Printer"},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert Machine.objects.filter(makerspace=makerspace, name="Workshop Printer").exists()


def test_guard_requires_an_open_transaction_to_be_meaningful():
    # select_for_update outside atomic() raises rather than silently not locking --
    # a guard that quietly stopped locking would be worse than no guard.
    from django.db.transaction import TransactionManagementError

    makerspace = space("race-atomic", "events")
    with pytest.raises(TransactionManagementError):
        require_module_locked(makerspace, "events")
