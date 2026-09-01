"""ON/OFF contracts for the optional payments module.

Payments is deliberately asymmetric: OFF suppresses new online charges, but existing
financial rows, provider callbacks, and staff cash reconciliation must remain usable.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DrfValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.bookings.models import BookableSpace, Booking
from apps.events.models import Event, EventRegistration
from apps.inventory.models import InventoryProduct
from apps.machines.models import (
    Machine, MachineServiceRequest, MachineType, MakerspaceMachineTypePricing,
    ServiceBucket,
)
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.module_install import install_module, uninstall_module
from apps.makerspaces.module_registry import core_module_keys, with_dependencies
from apps.payments.availability import online_payments_enabled
from apps.payments.models import MakerspacePaymentSettings, Payment
from tests.return_helpers import authenticated_client, make_member


pytestmark = pytest.mark.django_db

CORE = frozenset(core_module_keys())
DOMAIN_MODULES = {
    "bookings": {"bookings"},
    "events": {"events"},
    "machines": {"machines", "machine_service"},
    "membership": {"membership"},
}


def _configured_space(slug, domain, *, payments_on):
    # Dependency-closed, exactly as `profile_modules` and `install_module` build a set.
    # A raw union can express `bookings` without `membership`, which validation rejects.
    modules = sorted(with_dependencies(CORE | DOMAIN_MODULES[domain] | {"payments"}))
    space = Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=modules,
        enabled_features=["payments.enabled", f"payments.{domain}"],
        public_inventory_enabled=True,
    )
    settings = MakerspacePaymentSettings(makerspace=space)
    settings.set_stripe_secret_key("sk_test_offstate")
    settings.set_stripe_webhook_secret("whsec_test_offstate")
    settings.save()
    if not payments_on:
        # Exercise the production uninstall path, including dependent-feature pruning.
        uninstall_module(space, "payments")
    return space


def _invoke_charge_caller(domain, space, actor):
    """Create a valid domain subject, then call its real best-effort payment seam."""
    now = timezone.now() + timedelta(days=1)
    if domain == "bookings":
        from apps.bookings.service_payments import create_for_confirmed_booking

        bookable = BookableSpace.objects.create(
            makerspace=space, name="Paid room", payment_amount=Decimal("10.00")
        )
        subject = Booking.objects.create(
            space=bookable,
            member=actor,
            name=actor.username,
            email=actor.email,
            phone="1",
            starts_at=now,
            ends_at=now + timedelta(hours=1),
        )
        return subject, create_for_confirmed_booking(subject, actor)
    if domain == "events":
        from apps.events.service_payments import create_for_registered_registration

        event = Event.objects.create(
            makerspace=space,
            title="Paid event",
            starts_at=now,
            ends_at=now + timedelta(hours=1),
            payment_amount=Decimal("10.00"),
        )
        subject = EventRegistration.objects.create(
            event=event,
            member=actor,
            name=actor.username,
            email=actor.email,
            phone="1",
        )
        return subject, create_for_registered_registration(subject, actor)
    if domain == "membership":
        from apps.makerspaces.membership_payments import create_for_active_membership

        space.membership_dues_amount = Decimal("10.00")
        space.save(update_fields=["membership_dues_amount", "updated_at"])
        subject = MakerspaceMembership.objects.get(makerspace=space, user=actor)
        return subject, create_for_active_membership(subject, actor)

    from apps.machines.service_payments import create_for_completed_request

    machine_type = MachineType.objects.create(
        makerspace=space, slug=f"paid-{space.pk}", name="Paid machine type"
    )
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Paid machine"
    )
    bucket = ServiceBucket.objects.create(machine=machine, name="Service Requests")
    subject = MachineServiceRequest.objects.create(
        bucket=bucket,
        makerspace=space,
        requester=actor,
        member=actor,
        assigned_machine=machine,
        title="Paid machine job",
        actual_minutes=2,
    )
    MakerspaceMachineTypePricing.objects.create(
        makerspace=space,
        machine_type=machine_type,
        rate_per_unit=Decimal("4.00"),
        flat_fee=Decimal("2.00"),
        payment_enabled=True,
    )
    return subject, create_for_completed_request(subject, actor)


@pytest.mark.parametrize("domain", tuple(DOMAIN_MODULES))
def test_payments_off_makes_each_online_charge_caller_degrade_without_raising(domain):
    """Domain success cannot depend on billing: OFF returns no charge, not an error."""
    space = _configured_space(f"money-off-{domain}", domain, payments_on=False)
    actor = make_member(f"money-off-{domain}-member", space)

    subject, result = _invoke_charge_caller(domain, space, actor)

    assert online_payments_enabled(space, domain) is False
    assert result is None
    assert type(subject).objects.filter(pk=subject.pk).exists()
    assert not Payment.objects.filter(makerspace=space).exists()


@pytest.mark.parametrize("domain", tuple(DOMAIN_MODULES))
def test_payments_on_allows_each_online_charge_caller_to_create_its_payment(domain):
    """The OFF assertion is meaningful only if the same configured seam works when ON."""
    space = _configured_space(f"money-on-{domain}", domain, payments_on=True)
    actor = make_member(f"money-on-{domain}-member", space)

    subject, result = _invoke_charge_caller(domain, space, actor)

    assert online_payments_enabled(space, domain) is True
    assert result is not None
    assert result.subject_id == subject.pk
    assert result.status == Payment.Status.PENDING


def test_payments_module_gate_refuses_off_and_accepts_on():
    """Payments uses this gate as a silent new-charge predicate, not an HTTP deletion."""
    space = _configured_space("money-explicit-gate", "bookings", payments_on=False)

    with pytest.raises(DrfValidationError, match="payments is disabled"):
        require_module(space, "payments")

    install_module(space, "payments")
    assert require_module(space, "payments") == space


def _existing_membership_payment(space, actor, *, session_id):
    membership = MakerspaceMembership.objects.get(makerspace=space, user=actor)
    return Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=membership.pk,
        member=actor,
        amount="12.50",
        currency="usd",
        created_by=actor,
        stripe_checkout_session_id=session_id,
    )


def test_payments_off_still_lets_the_webhook_settle_an_existing_charge(monkeypatch):
    """The provider may have taken money before uninstall; its callback must still win."""
    space = _configured_space("money-webhook-off", "membership", payments_on=True)
    actor = make_member("money-webhook-off-member", space)
    payment = _existing_membership_payment(space, actor, session_id="cs_offstate")
    event = {
        "id": "evt_offstate",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_offstate", "payment_status": "paid"}},
    }
    uninstall_module(space, "payments")
    monkeypatch.setattr("apps.payments.views.construct_event", lambda *_args: event)

    response = APIClient().post(
        reverse("stripe-webhook", args=[space.public_code]),
        b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="verified-by-test-double",
    )

    payment.refresh_from_db()
    assert response.status_code == 200
    assert payment.status == Payment.Status.PAID_ONLINE


def test_payments_off_still_lets_staff_record_offline_money():
    """Cash reconciliation is the documented substitute when online charging is OFF."""
    space = _configured_space("money-offline-off", "membership", payments_on=True)
    manager = make_member("money-offline-off-manager", space)
    payment = _existing_membership_payment(space, manager, session_id=None)
    uninstall_module(space, "payments")

    response = authenticated_client(manager).post(
        reverse(
            "payment-reconciliation-mark-offline",
            args=[space.pk, payment.pk],
        )
    )

    payment.refresh_from_db()
    assert response.status_code == 200
    assert payment.status == Payment.Status.PAID_OFFLINE


def test_payments_off_leaves_the_complete_core_loan_spine_working():
    """Billing is optional and must never become an undeclared dependency of lending."""
    space = Makerspace.objects.create(
        name="Money off loan spine",
        slug="money-off-loan-spine",
        enabled_modules=sorted(CORE),
        public_inventory_enabled=True,
    )
    product = InventoryProduct.objects.create(
        makerspace=space,
        name="Torque wrench",
        total_quantity=3,
        available_quantity=3,
        is_public=True,
    )
    requester = User.objects.create_user(
        username="money-off-requester",
        email="money-off-requester@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )
    client = authenticated_client(requester)

    catalog = APIClient().get(reverse("inventory:public-inventory", args=[space.slug]))
    assert catalog.status_code == 200, catalog.data
    submitted = client.post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        {
            "requested_for": "Module independence check",
            "items": [{"product_id": product.pk, "quantity": 1}],
        },
        format="json",
    )
    assert submitted.status_code == 201, submitted.data
    staff = User.objects.create_user(
        username="money-off-staff",
        email="money-off-staff@example.test",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
    )
    staff_client = authenticated_client(staff)
    pending = staff_client.get(
        reverse("hardware_requests:pending-requests", args=[space.pk])
    )
    assert pending.status_code == 200, pending.data
    assert pending.data["count"] == 1
    accepted = staff_client.post(
        reverse(
            "hardware_requests:request-accept",
            args=[pending.data["results"][0]["id"]],
        ),
        {},
        format="json",
    )
    assert accepted.status_code == 200, accepted.data
    assert accepted.data["status"] == "accepted"
    public_status = APIClient().get(
        reverse(
            "hardware_requests:request-status",
            args=[submitted.data["public_token"]],
        )
    )

    assert "payments" not in space.enabled_modules
    assert public_status.status_code == 200, public_status.data
