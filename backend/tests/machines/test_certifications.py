"""Certification gating: off by default, fails closed when on, bypass is audited."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.audit.models import AuditLog
from apps.bookings.models import Booking
from apps.machines import service_workflow_actions as service_workflow
from apps.machines.models import CertificationGrant, Machine
from tests.module_helpers import disable_module
from tests.machines.certification_helpers import (
    _bookable,
    _book,
    _certification,
    _machine_type,
    _manager,
    _member,
    _space,
    _submit,
)

pytestmark = pytest.mark.django_db


# --- Toggle off ---------------------------------------------------------------

def test_feature_off_means_no_gate_at_all():
    space = _space("cert-off", certifications=False)
    machine_type = _machine_type(space)
    _certification(space, machine_type)
    member, _ = _member(space, "cert-off-member")
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Laser 1"
    )

    assert _submit(machine, member).pk is not None
    booking = _book(_bookable(space, machine_type), member)
    assert booking.status == Booking.Status.CONFIRMED


# --- Toggle on, no grant ------------------------------------------------------

def test_missing_grant_refuses_booking_with_the_typed_detail():
    space = _space("cert-on-booking")
    machine_type = _machine_type(space)
    _certification(space, machine_type, name="Laser induction")
    member, _ = _member(space, "cert-on-booking-member")

    with pytest.raises(PermissionDenied) as excinfo:
        _book(_bookable(space, machine_type), member)

    detail = excinfo.value.detail
    assert detail["code"] == "certification_required"
    assert [str(name) for name in detail["certifications"]] == ["Laser induction"]
    assert not Booking.objects.exists()


def test_missing_grant_refuses_service_submit_with_the_typed_detail():
    space = _space("cert-on-service")
    machine_type = _machine_type(space)
    _certification(space, machine_type, name="Laser induction")
    member, _ = _member(space, "cert-on-service-member")
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Laser 1"
    )

    with pytest.raises(PermissionDenied) as excinfo:
        _submit(machine, member)

    assert excinfo.value.detail["code"] == "certification_required"
    assert [str(n) for n in excinfo.value.detail["certifications"]] == ["Laser induction"]


def test_purpose_flags_are_independent():
    """A booking-only requirement must not gate a service request, and vice versa."""
    space = _space("cert-purpose")
    machine_type = _machine_type(space)
    _certification(
        space, machine_type, name="Booking only",
        is_required_for_service=False, is_required_for_booking=True,
    )
    member, _ = _member(space, "cert-purpose-member")
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Laser 1"
    )

    assert _submit(machine, member).pk is not None
    with pytest.raises(PermissionDenied):
        _book(_bookable(space, machine_type), member)


# --- Grant states -------------------------------------------------------------

def test_live_grant_allows_both_surfaces():
    space = _space("cert-granted")
    machine_type = _machine_type(space)
    certification = _certification(space, machine_type)
    member, membership = _member(space, "cert-granted-member")
    CertificationGrant.objects.create(
        certification_type=certification, membership=membership
    )
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Laser 1"
    )

    assert _submit(machine, member).pk is not None
    assert _book(_bookable(space, machine_type), member).pk is not None


def test_expired_grant_is_refused():
    space = _space("cert-expired")
    machine_type = _machine_type(space)
    certification = _certification(space, machine_type)
    member, membership = _member(space, "cert-expired-member")
    CertificationGrant.objects.create(
        certification_type=certification,
        membership=membership,
        expires_at=timezone.now() - timedelta(days=1),
    )

    with pytest.raises(PermissionDenied) as excinfo:
        _book(_bookable(space, machine_type), member)
    assert excinfo.value.detail["code"] == "certification_required"


def test_revoked_grant_is_refused():
    space = _space("cert-revoked")
    machine_type = _machine_type(space)
    certification = _certification(space, machine_type)
    member, membership = _member(space, "cert-revoked-member")
    CertificationGrant.objects.create(
        certification_type=certification,
        membership=membership,
        revoked_at=timezone.now() - timedelta(hours=1),
    )
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Laser 1"
    )

    with pytest.raises(PermissionDenied):
        _submit(machine, member)


def test_inactive_certification_type_stops_gating():
    space = _space("cert-inactive")
    machine_type = _machine_type(space)
    _certification(space, machine_type, is_active=False)
    member, _ = _member(space, "cert-inactive-member")

    assert _book(_bookable(space, machine_type), member).pk is not None


# --- Override -----------------------------------------------------------------

def test_manager_override_passes_and_is_audited():
    space = _space("cert-override")
    machine_type = _machine_type(space)
    certification = _certification(space, machine_type)
    member, _ = _member(space, "cert-override-member")
    manager, _role = _manager(space, "cert-override-manager", machine_type)
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Laser 1"
    )

    request = service_workflow.submit(
        machine, member, member=member, actor=manager,
        requester_name="Member", contact_email="member@example.test",
        contact_phone="123", title="Cut this",
        certification_override_reason="Trained today, paperwork pending",
    )

    assert request.pk is not None
    entry = AuditLog.objects.filter(action="certification.override").get()
    assert entry.actor_id == manager.pk
    assert entry.makerspace_id == space.pk
    assert entry.meta["reason"] == "Trained today, paperwork pending"
    assert entry.meta["certification_type_id"] == certification.pk


def test_override_without_type_authority_is_still_refused():
    space = _space("cert-override-denied")
    machine_type = _machine_type(space)
    other_type = _machine_type(space, "Printer")
    _certification(space, machine_type)
    member, _ = _member(space, "cert-override-denied-member")
    # Scoped to a DIFFERENT machine type: holding MANAGE_MACHINES is not enough.
    outsider, _role = _manager(space, "cert-override-denied-mgr", other_type)
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Laser 1"
    )

    with pytest.raises(PermissionDenied):
        service_workflow.submit(
            machine, member, member=member, actor=outsider,
            requester_name="Member", contact_email="member@example.test",
            contact_phone="123", title="Cut this",
            certification_override_reason="Let me through",
        )
    assert not AuditLog.objects.filter(action="certification.override").exists()


def test_override_needs_a_reason():
    space = _space("cert-override-noreason")
    machine_type = _machine_type(space)
    _certification(space, machine_type)
    member, _ = _member(space, "cert-override-noreason-member")
    manager, _role = _manager(space, "cert-override-noreason-mgr", machine_type)

    with pytest.raises(PermissionDenied):
        _book(_bookable(space, machine_type), member, actor=manager)


# --- Bookings without the machines module ------------------------------------

def test_bookings_only_makerspace_still_books():
    """No `machines` module, no machine_type on the space: gating must not appear."""
    space = _space("cert-bookings-only", modules=("bookings",), certifications=False)
    # A fresh makerspace starts with EVERY module on; turn machines off explicitly.
    disable_module(space, "machines")
    space.refresh_from_db()
    member, _ = _member(space, "cert-bookings-only-member")

    booking = _book(_bookable(space, None), member)

    assert booking.status == Booking.Status.CONFIRMED
    assert space.enabled_modules.count("machines") == 0
