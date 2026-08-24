from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.backup.raw_projection import raw_records
from apps.boxes.models import Box
from apps.events.models import Event, EventCollaborator, EventRegistration
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from apps.operations.models import StockTransfer, StockTransferLine
from apps.payments.models import Payment
from apps.tenant_migration.tenant_dump_cross_tenant import (
    CROSS_TENANT_EDGE_RULES,
    PAYMENT_CLEARED_VALUES,
    inspect_cross_tenant_source,
    project_cross_tenant_values,
    validate_cross_tenant_registry,
)
from apps.tenant_migration.tenant_dump_cross_tenant_verify import (
    verify_cross_tenant_projection,
)
from apps.tenant_migration.tenant_dump_errors import TenantDumpDispositionRefused
from apps.tenant_migration.tenant_dump_raw import sanitize_record


pytestmark = pytest.mark.django_db


def _space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def _user(name):
    return User.objects.create_user(username=name, email=f"{name}@example.test")


def _payment(space, actor, status):
    row = Payment(
        makerspace=space,
        subject_type=Payment.SubjectType.BOOKING,
        subject_id=9000 + len(status),
        subject_label="Historical booking",
        member=actor,
        amount=Decimal("42.75"),
        currency="inr",
        status=status,
        provider=Payment.Provider.RAZORPAY,
        via_makerspace=space,
        external_order_id=f"order-{status}",
        external_payment_id=f"payment-{status}",
        checkout_url=f"https://checkout.example/{status}",
        stripe_provider=Payment.StripeProvider.CONNECT,
        stripe_connected_account_id=f"acct-{status}",
        stripe_application_fee_amount=71,
        online_rail=Payment.OnlineRail.CHECKOUT,
        stripe_checkout_session_id=f"session-{status}",
        stripe_checkout_url=f"https://stripe.example/{status}",
        stripe_payment_intent_id=f"intent-{status}",
        created_by=actor,
    )
    Payment.objects.bulk_create([row])
    return Payment.objects.get(external_order_id=f"order-{status}")


@pytest.mark.parametrize(
    "status",
    sorted(set(Payment.Status.values) - {Payment.Status.PENDING}),
)
def test_terminal_payment_preserves_history_and_clears_every_live_handle(status):
    space = _space(f"payment-{status}")
    actor = _user(f"payment-{status}-actor")
    payment = _payment(space, actor, status)
    source = raw_records(Payment.objects.filter(pk=payment.pk), Payment)[0]

    projected = sanitize_record(Payment, source).values

    assert projected["status"] == status
    assert projected["amount"] == Decimal("42.75")
    assert projected["currency"] == "inr"
    assert projected["provider"] == Payment.Provider.RAZORPAY
    assert projected["subject_type"] == Payment.SubjectType.BOOKING
    assert projected["subject_id"] == payment.subject_id
    assert projected["subject_label"] == "Historical booking"
    for field_name, value in PAYMENT_CLEARED_VALUES.items():
        column = Payment._meta.get_field(
            field_name.removesuffix("_id")
            if field_name == "via_makerspace_id"
            else field_name
        ).column
        assert projected[column] == value


def test_one_pending_payment_refuses_the_entire_source_projection():
    space = _space("pending-payment")
    actor = _user("pending-payment-actor")
    _payment(space, actor, Payment.Status.PENDING)

    with pytest.raises(TenantDumpDispositionRefused) as refused:
        inspect_cross_tenant_source(space.pk)

    assert refused.value.reason_code == "pending_payment"


def test_foreign_registration_payment_route_refuses_while_payment_is_pending():
    host = _space("pending-registration-host")
    via = _space("pending-registration-via")
    actor = _user("pending-registration-actor")
    starts_at = timezone.now()
    event = Event.objects.create(
        makerspace=host,
        title="Pending registration",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
    )
    registration = EventRegistration.objects.create(
        event=event,
        name="Pending member",
        email="pending-member@example.test",
        phone="",
        member=actor,
        registered_via_makerspace=via,
        payment_via_makerspace=via,
    )
    payment = _payment(host, actor, Payment.Status.PENDING)
    Payment.objects.filter(pk=payment.pk).update(
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=registration.pk,
        via_makerspace=via,
    )

    with pytest.raises(TenantDumpDispositionRefused) as refused:
        inspect_cross_tenant_source(host.pk)

    assert refused.value.reason_code == "pending_payment"


def test_collaboration_and_stock_transfer_losses_are_recorded_without_foreign_ids():
    space = _space("cross-source")
    foreign = _space("cross-foreign")
    actor = _user("cross-actor")
    starts_at = timezone.now()
    event = Event.objects.create(
        makerspace=space,
        title="Collaborative event",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
    )
    collaborator = EventCollaborator.objects.create(
        event=event, makerspace=foreign, invited_by=actor
    )
    source_box = Box.objects.create(makerspace=space, code="SOURCE")
    foreign_box = Box.objects.create(makerspace=foreign, code="FOREIGN")
    source_product = InventoryProduct.objects.create(
        makerspace=space, name="Source stock", total_quantity=2, available_quantity=2
    )
    foreign_product = InventoryProduct.objects.create(
        makerspace=foreign, name="Foreign stock", total_quantity=2, available_quantity=2
    )
    outbound = StockTransfer.objects.create(
        makerspace=space,
        source_makerspace=space,
        source_container=source_box,
        destination_makerspace=foreign,
        destination_container=foreign_box,
        created_by=actor,
        reason="Outbound",
    )
    StockTransferLine.objects.create(
        transfer=outbound, product=source_product, quantity=1
    )
    inbound = StockTransfer.objects.create(
        makerspace=foreign,
        source_makerspace=foreign,
        source_container=foreign_box,
        destination_makerspace=space,
        destination_container=source_box,
        created_by=actor,
        reason="Inbound",
    )
    inbound_line = StockTransferLine.objects.create(
        transfer=inbound, product=foreign_product, quantity=1
    )

    facts = inspect_cross_tenant_source(space.pk)

    assert inbound_line.pk in facts.dropped_transfer_line_ids
    assert {
        (item["model_label"], item["source_row_pk"], item["field_name"])
        for item in facts.lost_edges
    } >= {
        ("events.EventCollaborator", collaborator.pk, "makerspace"),
        ("operations.StockTransfer", outbound.pk, "destination_makerspace"),
        ("operations.StockTransfer", outbound.pk, "destination_container"),
        ("operations.StockTransfer", inbound.pk, "makerspace"),
        ("operations.StockTransferLine", inbound_line.pk, "transfer"),
    }
    assert all("makerspace_id" not in item for item in facts.lost_edges)

    source = raw_records(StockTransfer.objects.filter(pk=outbound.pk), StockTransfer)[0]
    sanitized = sanitize_record(StockTransfer, source)
    projected = project_cross_tenant_values(
        StockTransfer, sanitized.values, source, space.pk
    )
    assert projected["source_makerspace_id"] == space.pk
    assert projected["source_container_id"] == source_box.pk
    assert projected["destination_makerspace_id"] is None
    assert projected["destination_container_id"] is None


def test_event_registration_routing_is_nulled():
    host = _space("registration-host")
    via = _space("registration-via")
    actor = _user("registration-actor")
    starts_at = timezone.now()
    event = Event.objects.create(
        makerspace=host,
        title="Registration route",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
    )
    registration = EventRegistration.objects.create(
        event=event,
        name="Member",
        email="member@example.test",
        phone="+1 555 0199",
        member=actor,
        registered_via_makerspace=via,
        payment_via_makerspace=via,
    )
    source = raw_records(
        EventRegistration.objects.filter(pk=registration.pk), EventRegistration
    )[0]

    projected = sanitize_record(EventRegistration, source).values

    assert projected["registered_via_makerspace_id"] is None
    assert projected["payment_via_makerspace_id"] is None


def test_cross_tenant_registry_refuses_an_unclassified_edge():
    changed = dict(CROSS_TENANT_EDGE_RULES)
    changed.pop(("payments.Payment", "via_makerspace"))

    with pytest.raises(TenantDumpDispositionRefused) as refused:
        validate_cross_tenant_registry(changed)

    assert refused.value.reason_code == "unclassified_cross_tenant_edge"


def test_independent_projection_verifier_accepts_only_closed_terminal_history():
    space = _space("verified-payment")
    actor = _user("verified-payment-actor")
    payment = _payment(space, actor, Payment.Status.PAID_ONLINE)
    Payment.objects.filter(pk=payment.pk).update(**PAYMENT_CLEARED_VALUES)

    assert verify_cross_tenant_projection("default", space.pk) is True
