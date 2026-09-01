"""Endpoint-level acceptance proof for account-less Phase 7 claim sessions."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.bookings.models import BookableSpace, Booking
from apps.boxes.models import QrCode, QrScanEvent
from apps.evidence.models import EvidencePhoto
from apps.events.models import Event, EventRegistration
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.inventory.models import InventoryProduct
from apps.machines.models import Machine, MachineServiceRequest, MachineType
from apps.payments.models import MakerspacePaymentSettings, Payment
from apps.presence.models import PresenceSession
from tests.accounts.claim_helpers_p7 import redeemed_claim, start_claim_presence

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def bounded_claim_deadline(settings):
    settings.MEMBER_CLAIM_SESSION_TTL_SECONDS = 10 * 60


def product(space, suffix, **values):
    defaults = dict(
        makerspace=space,
        name=f"Claim tool {suffix}",
        total_quantity=2,
        available_quantity=2,
        is_public=True,
    )
    defaults.update(values)
    return InventoryProduct.objects.create(**defaults)


def claim_audit(harness, action):
    entry = AuditLog.objects.filter(action=action, actor=harness.member).latest("id")
    assert entry.meta["claim_session_id"] == str(harness.claim.session_id)
    assert entry.meta["claim_issued_by_id"] == harness.staff.pk


def evidence_url(client, space, evidence_type):
    response = client.post(
        f"/api/v1/public/{space.slug}/tools/evidence-url",
        {"evidence_type": evidence_type, "content_type": "image/jpeg"},
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data["evidence_id"]


def test_claim_completes_all_three_public_self_checkout_surfaces(monkeypatch):
    harness = redeemed_claim("accept-self")
    start_claim_presence(harness)
    monkeypatch.setattr(
        "apps.hardware_requests.self_checkout_views.presigned_upload",
        lambda *_args: {"url": "https://storage.test/upload", "fields": {}},
    )
    item = product(harness.space, "self", public_self_checkout_enabled=True)
    qr = QrCode.objects.create(
        makerspace=harness.space,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=item.pk,
    )

    issued = harness.claim_client.post(
        f"/api/v1/public/{harness.space.slug}/tools/checkout",
        {"payload": qr.payload, "evidence_id": evidence_url(
            harness.claim_client, harness.space, EvidencePhoto.EvidenceType.ISSUE
        )},
        format="json",
    )
    assert issued.status_code == 201, issued.data
    returned = harness.claim_client.post(
        f"/api/v1/public/{harness.space.slug}/tools/return",
        {
            "payload": qr.payload,
            "evidence_id": evidence_url(
                harness.claim_client, harness.space, EvidencePhoto.EvidenceType.RETURN
            ),
            "remark": "Returned at the desk.",
        },
        format="json",
    )

    assert returned.status_code == 200, returned.data
    assert PublicToolLoan.objects.get().status == PublicToolLoan.Status.RETURNED
    assert set(QrScanEvent.objects.values_list("context", flat=True)) == {
        QrScanEvent.Context.ISSUE,
        QrScanEvent.Context.RETURN,
    }
    claim_audit(harness, "public_tool.checked_out")
    claim_audit(harness, "public_tool.returned")


def test_staff_can_directly_hand_out_to_claim_member_with_claim_presence():
    harness = redeemed_claim("accept-handout")
    presence = start_claim_presence(harness)
    item = product(harness.space, "handout")
    evidence = EvidencePhoto.objects.create(
        makerspace=harness.space,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=f"evidence/{harness.space.pk}/issue/direct.jpg",
        uploaded_by=harness.staff,
    )

    response = harness.staff_client.post(
        f"/api/v1/admin/makerspace/{harness.space.pk}/direct-loans",
        {
            "borrower_id": harness.member.pk,
            "evidence_id": evidence.pk,
            "items": [{"product_id": item.pk, "quantity": 1}],
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    loan = PublicToolLoan.objects.get(source=PublicToolLoan.Source.ADMIN_DIRECT)
    assert loan.requester == harness.member
    assert loan.request.issue_evidence == evidence
    assert presence.created_via_claim_session == harness.claim


def test_claim_submits_a_public_hardware_request():
    harness = redeemed_claim("accept-request")
    start_claim_presence(harness)
    item = product(harness.space, "request")

    response = harness.claim_client.post(
        f"/api/v1/public/{harness.space.slug}/requests",
        {"requested_for": "Bench work", "items": [{"product_id": item.pk, "quantity": 1}]},
        format="json",
    )

    assert response.status_code == 201, response.data
    request = HardwareRequest.objects.get()
    assert request.requester == harness.member
    assert request.status == HardwareRequest.Status.PENDING_APPROVAL
    claim_audit(harness, "request.submitted")


def test_claim_creates_a_public_booking():
    harness = redeemed_claim("accept-booking")
    start_claim_presence(harness)
    bookable = BookableSpace.objects.create(
        makerspace=harness.space, name="Claim room", is_public=True
    )
    starts_at = timezone.now() + timedelta(days=1)

    response = harness.claim_client.post(
        f"/api/v1/public/{harness.space.slug}/spaces/{bookable.public_token}/book/",
        {
            "starts_at": starts_at.isoformat(),
            "ends_at": (starts_at + timedelta(hours=1)).isoformat(),
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert Booking.objects.get().member == harness.member
    claim_audit(harness, "booking.created")


def test_claim_reads_public_events_and_registers_as_the_member():
    harness = redeemed_claim("accept-event")
    starts_at = timezone.now() + timedelta(days=1)
    event = Event.objects.create(
        makerspace=harness.space,
        title="Claim workshop",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        is_public=True,
        status=Event.Status.PUBLISHED,
    )

    listed = harness.claim_client.get(f"/api/v1/public/{harness.space.slug}/events/")
    registered = harness.claim_client.post(
        f"/api/v1/public/{harness.space.slug}/events/{event.public_token}/register/",
        {},
        format="json",
    )

    assert listed.status_code == 200
    assert [row["title"] for row in listed.data] == [event.title]
    assert registered.status_code == 201, registered.data
    assert EventRegistration.objects.get(event=event).member == harness.member
    claim_audit(harness, "event.registration_created")


def test_claim_submits_machine_service_and_reads_it_in_member_activity():
    harness = redeemed_claim("accept-machine")
    start_claim_presence(harness)
    machine_type = MachineType.objects.create(
        makerspace=harness.space, slug="claim-machine", name="Claim machine"
    )
    machine = Machine.objects.create(
        makerspace=harness.space,
        machine_type=machine_type,
        name="Claim laser",
        is_public=True,
    )

    submitted = harness.claim_client.post(
        f"/api/v1/public/{harness.space.slug}/machine-service-requests",
        {"machine_id": machine.pk, "title": "Align optics"},
        format="json",
    )
    activity = harness.claim_client.get(
        f"/api/v1/member/makerspaces/{harness.space.pk}/activity"
    )

    assert submitted.status_code == 201, submitted.data
    assert activity.status_code == 200, activity.data
    row = MachineServiceRequest.objects.get()
    assert row.member == harness.member
    assert [item["title"] for item in activity.data["machine_service_requests"]] == [row.title]
    claim_audit(harness, "machine_service.submitted")


def test_claim_reaches_member_area_and_checks_out_a_locally_owned_charge(monkeypatch):
    harness = redeemed_claim("accept-payment")
    settings = MakerspacePaymentSettings(makerspace=harness.space)
    settings.set_stripe_secret_key("sk_test_claim")
    settings.set_stripe_webhook_secret("whsec_claim")
    settings.save()
    payment = Payment.objects.create(
        makerspace=harness.space,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=harness.membership.pk,
        member=harness.member,
        amount=Decimal("12.00"),
        currency="usd",
        created_by=harness.staff,
    )
    monkeypatch.setattr(
        "apps.payments.services.stripe_client.create_checkout_session",
        lambda *_args, **_kwargs: {
            "id": "cs_claim_acceptance",
            "url": "https://checkout.stripe.test/claim",
        },
    )

    profile = harness.claim_client.get(
        f"/api/v1/member/makerspaces/{harness.space.pk}/profile"
    )
    history = harness.claim_client.get(
        f"/api/v1/member/makerspaces/{harness.space.pk}/payments"
    )
    checkout = harness.claim_client.post(
        f"/api/v1/member/makerspaces/{harness.space.pk}/payments/{payment.pk}/checkout"
    )

    assert profile.status_code == 200, profile.data
    assert profile.data["membership_id"] == harness.membership.pk
    assert [row["id"] for row in history.data] == [payment.pk]
    assert checkout.status_code == 200, checkout.data
    assert checkout.data["checkout_url"] == "https://checkout.stripe.test/claim"
    claim_audit(harness, "payment.checkout_created")
    assert PresenceSession.objects.filter(created_via_claim_session=harness.claim).count() == 0
