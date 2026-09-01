"""Per-module data purge (plan A9).

Purge is the irreversible second step after uninstall, not an alternative to it.
These tests pin the guardrails that make it safe to expose at all, and the two
easy-to-miss deletions -- generic-keyed Payments and FK-less blind-index rows.
"""

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import BookableSpace, Booking
from apps.events.models import Event, EventRegistration
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MakerspaceWaiver,
    MemberProfile,
    MemberProject,
    MembershipRequest,
)
from apps.makerspaces.module_install import install_module, uninstall_module
from tests.module_helpers import disable_module
from apps.makerspaces.module_purge import purge_module, purgeable_modules
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db(transaction=True)


def superadmin(name="purge-admin"):
    return User.objects.create_superuser(username=name, email=f"{name}@example.test", password="password")


def space(slug, *modules):
    item = Makerspace.objects.create(name=slug.title(), slug=slug)
    for key in modules:
        install_module(item, key)
    item.refresh_from_db()
    return item


def an_event(makerspace, title="Workshop"):
    now = timezone.now()
    return Event.objects.create(
        makerspace=makerspace, title=title, description="",
        starts_at=now + timezone.timedelta(days=1),
        ends_at=now + timezone.timedelta(days=1, hours=2),
        location="Lab", capacity=0, is_public=True,
    )


# --- guardrails --------------------------------------------------------------


def test_purge_requires_the_module_to_be_uninstalled_first():
    # Uninstall is reversible and retains data; purge destroys it. Requiring the order
    # means no single command both hides and destroys.
    makerspace = space("purge-installed", "events")
    an_event(makerspace)

    with pytest.raises(ValidationError) as exc:
        purge_module(makerspace, "events", superadmin())

    assert "still installed" in " ".join(exc.value.messages)
    assert Event.objects.filter(makerspace=makerspace).exists()


def test_purge_is_superadmin_only():
    makerspace = space("purge-nonadmin", "events")
    an_event(makerspace)
    uninstall_module(makerspace, "events")
    ordinary = User.objects.create_user(username="ordinary", email="o@example.test", password="password")

    with pytest.raises(ValidationError):
        purge_module(makerspace, "events", ordinary)

    assert Event.objects.filter(makerspace=makerspace).exists()


def test_core_and_inseparable_modules_explain_why_they_cannot_be_purged():
    makerspace = space("purge-core")

    with pytest.raises(ValidationError) as core:
        purge_module(makerspace, "qr_management", superadmin("core-admin"))
    assert "Core module" in " ".join(core.value.messages)

    with pytest.raises(ValidationError) as machines:
        purge_module(makerspace, "machines", superadmin("machines-admin"))
    # The operator is told what to do instead, not just refused.
    assert "machine_service" in " ".join(machines.value.messages)


def test_unknown_module_is_rejected():
    makerspace = space("purge-unknown")
    with pytest.raises(ValidationError):
        purge_module(makerspace, "not_a_module", superadmin("unknown-admin"))


# --- what actually gets deleted ----------------------------------------------


def test_purging_events_removes_events_and_registrations_but_keeps_the_payment():
    makerspace = space("purge-events", "events")
    actor = superadmin("events-admin")
    event = an_event(makerspace)
    registration = EventRegistration.objects.create(
        event=event, name="Ada", email="ada@example.test", phone="+10000000000"
    )
    payment = Payment.objects.create(
        makerspace=makerspace, subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=registration.pk, amount=10, currency="usd",
        status=Payment.Status.PENDING, created_by=actor,
        subject_label="Open Night",
    )
    uninstall_module(makerspace, "events")

    counts = purge_module(makerspace, "events", actor)

    assert not Event.objects.filter(makerspace=makerspace).exists()
    assert not EventRegistration.objects.filter(event__makerspace=makerspace).exists()
    # REVERSED DELIBERATELY. This used to assert the payment was destroyed with its
    # subject, on the reasoning that it would otherwise dangle. Switching a module off and
    # purging its rows is not a reason to destroy the record of money that really changed
    # hands: a receipt must stay visible and a pending charge must stay payable. The
    # dangling reference is handled instead -- `subject_label` is snapshotted at creation
    # and `Payment.clean()` tolerates a missing subject on an otherwise-unchanged row.
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING, "status must not be reset"
    assert "payments" not in counts, "no plan reports a payment delete any more"


def test_purging_one_module_leaves_another_modules_payments_intact():
    # The whole-makerspace purge deletes every Payment; a per-module purge must not.
    makerspace = space("purge-scoped", "events", "bookings")
    actor = superadmin("scoped-admin")
    event = an_event(makerspace)
    registration = EventRegistration.objects.create(
        event=event, name="Ada", email="ada@example.test", phone="+10000000000"
    )
    bookable = BookableSpace.objects.create(makerspace=makerspace, name="Bench")
    now = timezone.now()
    booking = Booking.objects.create(
        space=bookable, name="Grace", email="grace@example.test", phone="+10000000001",
        starts_at=now + timezone.timedelta(days=1),
        ends_at=now + timezone.timedelta(days=1, hours=1),
        status=Booking.Status.PENDING,
    )
    Payment.objects.create(
        makerspace=makerspace, subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=registration.pk, amount=10, currency="usd",
        status=Payment.Status.PENDING, created_by=actor,
    )
    booking_payment = Payment.objects.create(
        makerspace=makerspace, subject_type=Payment.SubjectType.BOOKING,
        subject_id=booking.pk, amount=20, currency="usd",
        status=Payment.Status.PENDING, created_by=actor,
    )
    uninstall_module(makerspace, "events")

    purge_module(makerspace, "events", actor)

    assert Payment.objects.filter(pk=booking_payment.pk).exists()
    assert BookableSpace.objects.filter(makerspace=makerspace).exists()


def test_purging_bookings_removes_spaces_and_bookings():
    makerspace = space("purge-bookings", "bookings")
    bookable = BookableSpace.objects.create(makerspace=makerspace, name="Bench")
    now = timezone.now()
    Booking.objects.create(
        space=bookable, name="Ada", email="ada@example.test", phone="+10000000000",
        starts_at=now + timezone.timedelta(days=1),
        ends_at=now + timezone.timedelta(days=1, hours=1),
        status=Booking.Status.PENDING,
    )
    uninstall_module(makerspace, "bookings")

    purge_module(makerspace, "bookings", superadmin("bookings-admin"))

    assert not BookableSpace.objects.filter(makerspace=makerspace).exists()
    assert not Booking.objects.filter(space__makerspace=makerspace).exists()


def test_purging_membership_keeps_waiver_evidence_but_removes_community_data():
    makerspace = space("purge-membership", "membership")
    member = User.objects.create_user(username="waiver-member", email="wm@example.test", password="password")
    waiver = MakerspaceWaiver.objects.create(makerspace=makerspace, version="1", body="Be careful", is_active=True)
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=member,
        assigned_role=MakerspaceRole.objects.get(makerspace=makerspace, slug="member"),
        status="active", accepted_waiver=waiver, waiver_accepted_at=timezone.now(),
        waiver_version_accepted="1",
    )
    profile = MemberProfile.objects.create(membership=membership)
    project = MemberProject.objects.create(profile=profile, title="Laser guide")
    request = MembershipRequest.objects.create(
        makerspace=makerspace,
        user=member,
        kind=MembershipRequest.Kind.REQUEST,
        state=MembershipRequest.State.REVOKED,
    )
    disable_module(makerspace, "membership")

    purge_module(makerspace, "membership", superadmin("membership-admin"))

    membership.refresh_from_db()
    assert MakerspaceMembership.objects.filter(pk=membership.pk).exists()
    assert membership.accepted_waiver_id == waiver.id
    assert membership.waiver_accepted_at is not None
    assert membership.waiver_version_accepted == "1"
    assert MakerspaceWaiver.objects.filter(pk=waiver.pk).exists()
    assert not MemberProfile.objects.filter(pk=profile.pk).exists()
    assert not MemberProject.objects.filter(pk=project.pk).exists()
    assert not MembershipRequest.objects.filter(pk=request.pk).exists()


def test_purging_machine_service_keeps_machines_module_data():
    """The `machines` module stays installed, so its rows must survive.

    Two PROTECT edges make this the sharpest boundary in the purge set: a manual
    usage entry pins the consumable pool it drew from, and a service-derived usage
    entry pins the request that produced it. Deleting pools (as the whole-makerspace
    purge does) would raise; leaving service-derived entries would strand the
    requester PII the purge exists to remove.
    """
    from apps.machines.models import (
        Machine,
        MachineConsumablePool,
        MachineServiceRequest,
        MachineType,
        MachineUsageEntry,
        ServiceQueue,
    )

    makerspace = space("purge-machine-service", "machines", "machine_service")
    actor = superadmin("machine-service-admin")
    machine_type = MachineType.objects.create(
        makerspace=makerspace, slug="laser", name="Laser Cutter"
    )
    machine = Machine.objects.create(
        makerspace=makerspace, machine_type=machine_type, name="Laser One"
    )
    pool = MachineConsumablePool.objects.create(
        makerspace=makerspace, machine=machine, material="pla",
        initial_grams=1000, remaining_grams=800,
    )
    queue = ServiceQueue.objects.create(
        makerspace=makerspace, machine_type=machine_type, name="Laser queue"
    )
    request = MachineServiceRequest.objects.create(
        makerspace=makerspace, queue=queue, requester=actor, title="Cut a panel",
        requester_name="Ada", contact_email="ada@example.test",
    )
    from_service = MachineUsageEntry.objects.create(
        machine=machine, hours=2, service_request=request, consumable_pool=pool,
        requester_name="Ada", contact_email="ada@example.test",
    )
    manual = MachineUsageEntry.objects.create(
        machine=machine, hours=1, consumable_pool=pool, note="Staff run"
    )
    # `printing` declares `requires_modules=("machine_service",)`, so it has to go first.
    uninstall_module(makerspace, "printing")
    uninstall_module(makerspace, "machine_service")

    counts = purge_module(makerspace, "machine_service", actor)

    assert not MachineServiceRequest.objects.filter(makerspace=makerspace).exists()
    assert not ServiceQueue.objects.filter(makerspace=makerspace).exists()
    # `machines` is still installed: its machine, its pool and its manually logged
    # hours are none of this module's business.
    assert Machine.objects.filter(pk=machine.pk).exists()
    assert MachineConsumablePool.objects.filter(pk=pool.pk).exists()
    assert MachineUsageEntry.objects.filter(pk=manual.pk).exists()
    # The service-derived entry carried the requester's name and email off the
    # request, so it goes with it.
    assert not MachineUsageEntry.objects.filter(pk=from_service.pk).exists()
    assert counts["machine_usage_entries"] == 1


def test_purging_an_empty_module_is_a_no_op_not_an_error():
    makerspace = space("purge-empty", "events")
    uninstall_module(makerspace, "events")

    assert purge_module(makerspace, "events", superadmin("empty-admin")) == {}


def test_every_purgeable_plan_names_a_registered_module():
    from apps.makerspaces.module_registry import BY_KEY, core_module_keys

    for item in purgeable_modules():
        assert item["key"] in BY_KEY, item["key"]
        assert item["key"] not in core_module_keys(), item["key"]
