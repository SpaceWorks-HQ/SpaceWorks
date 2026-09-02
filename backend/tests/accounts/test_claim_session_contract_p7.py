"""Security and lifetime contract for the bounded Phase 7 claim session."""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.claim_route_types import Refused
from apps.accounts.claim_routes import CLAIM_ROUTES
from apps.accounts.claim_tokens import ClaimAccessToken, ClaimRefreshToken
from apps.accounts.models import DeviceGrant, User
from apps.events.models import Event, EventRegistration
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MakerspaceWaiver,
    MemberProfile,
)
from apps.payments.models import Payment
from apps.presence import services as presence_services
from apps.presence.models import PresenceSession
from tests.accounts.claim_helpers_p7 import redeemed_claim, start_claim_presence

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def bounded_claim_deadline(settings):
    settings.MEMBER_CLAIM_SESSION_TTL_SECONDS = 10 * 60
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:5000"]


def test_refresh_rotation_preserves_one_absolute_expiry_forever():
    harness = redeemed_claim("contract-expiry")
    deadline = int(harness.claim.absolute_expires_at.timestamp())
    refresh_ids = []

    for _ in range(3):
        refresh = ClaimRefreshToken(
            harness.claim_client.cookies["refresh_token"].value
        )
        refresh_ids.append(str(refresh["jti"]))
        assert refresh["absolute_expires_at"] == deadline
        assert refresh["exp"] == deadline
        response = harness.claim_client.post(
            "/api/v1/auth/refresh",
            HTTP_X_REFRESH_CSRF="1",
            HTTP_ORIGIN="http://localhost:5000",
        )
        assert response.status_code == 200, response.data
        access = ClaimAccessToken(response.data["access"])
        assert access["absolute_expires_at"] == deadline
        harness.claim_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {response.data['access']}"
        )

    harness.claim.refresh_from_db()
    assert int(harness.claim.absolute_expires_at.timestamp()) == deadline
    assert len(set(refresh_ids)) == 3


ROUTE_KWARGS = {
    "social-oidc": {"slug": "example"},
    "social-provider-detail": {"provider": "google"},
    "device-grant-detail": {"grant_id": UUID(int=1)},
    "membership-invitation-claim": {"pk": 1},
    "membership-invitation-claim-legacy": {"pk": 1},
    "member-waiver-accept": {"makerspace_id": "claim"},
    "member-payment-mobile-intent": {
        "makerspace_id": "claim",
        "payment_id": 1,
    },
    "member-referrals": {"makerspace_id": "claim"},
    "member-collaborative-events": {"makerspace_id": "claim"},
    "member-collaborative-event-register": {
        "makerspace_id": "claim",
        "pk": 1,
    },
    "member-event-checkin-qr": {"makerspace_id": "claim", "pk": 1},
    "member-event-calendar": {"makerspace_id": "claim"},
    "member-event-calendar-feed": {"makerspace_id": "claim"},
    "member-event-feedback": {"makerspace_id": "claim", "pk": 1},
    "member-event-certificate-download": {"makerspace_id": "claim", "pk": 1},
    "public-membership-request": {"makerspace_slug": "claim"},
}
REFUSED_KEYS = sorted(
    (name, method)
    for (name, method), policy in CLAIM_ROUTES.items()
    if isinstance(policy, Refused)
)


@pytest.mark.parametrize("view_name,method", REFUSED_KEYS)
def test_every_refused_matrix_entry_returns_403(view_name, method):
    harness = redeemed_claim(f"refused-{REFUSED_KEYS.index((view_name, method))}")
    kwargs = {
        key: harness.space.pk if value == "claim" else value
        for key, value in ROUTE_KWARGS.get(view_name, {}).items()
    }
    url = reverse(view_name, kwargs=kwargs or None)

    if method in {"POST", "DELETE"}:
        response = harness.claim_client.generic(
            method, url, b"{}", content_type="application/json"
        )
    else:
        response = harness.claim_client.generic(method, url)

    assert response.status_code == 403, (view_name, method, response.data)
    assert not DeviceGrant.objects.filter(user=harness.member).exists()


def event(space, title):
    starts_at = timezone.now() + timedelta(days=1)
    return Event.objects.create(
        makerspace=space,
        title=title,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        is_public=True,
        status=Event.Status.PUBLISHED,
    )


def registration(event_row, harness, *, via):
    return EventRegistration.objects.create(
        event=event_row,
        member=harness.member,
        name=harness.member.display_name,
        email=harness.member.email,
        phone=harness.member.phone,
        registered_via_makerspace=via,
        status=EventRegistration.Status.ATTENDED,
    )


def payment(space, membership, registration_row, *, via=None):
    return Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=registration_row.pk,
        member=membership.user,
        via_makerspace=via,
        amount=Decimal("5.00"),
        currency="usd",
        created_by=membership.user,
    )


def test_mixed_ownership_reads_and_checkout_never_return_a_foreign_row():
    harness = redeemed_claim("contract-ownership")
    foreign = Makerspace.objects.create(name="Foreign claim host", slug="foreign-claim-host")
    MakerspaceMembership.objects.create(
        makerspace=foreign,
        user=harness.member,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=foreign, slug="member"),
    )
    local_registration = registration(event(harness.space, "Local event"), harness, via=harness.space)
    foreign_registration = registration(event(foreign, "Foreign event"), harness, via=harness.space)
    local_payment = payment(harness.space, harness.membership, local_registration)
    foreign_payment = payment(foreign, harness.membership, foreign_registration, via=harness.space)
    MemberProfile.objects.create(
        membership=harness.membership,
        is_visible=True,
        show_attended_events=True,
    )

    base = f"/api/v1/member/makerspaces/{harness.space.pk}"
    activity = harness.claim_client.get(f"{base}/activity")
    profile = harness.claim_client.get(f"{base}/profile")
    detail = harness.claim_client.get(f"{base}/directory/{harness.membership.pk}")
    history = harness.claim_client.get(f"{base}/payments")
    foreign_checkout = harness.claim_client.post(
        f"{base}/payments/{foreign_payment.pk}/checkout"
    )

    assert activity.status_code == profile.status_code == detail.status_code == 200
    assert [row["event_title"] for row in activity.data["event_registrations"]] == ["Local event"]
    assert profile.data["activity"]["events_registered"] == 1
    assert [row["title"] for row in detail.data["activity"]["recent_attended_events"]] == ["Local event"]
    assert [row["id"] for row in history.data] == [local_payment.pk]
    assert foreign_checkout.status_code == 404


def test_revocation_rejects_the_live_access_token_and_ends_only_claim_presence():
    harness = redeemed_claim("contract-revoke")
    ordinary = presence_services.start_session(harness.member, harness.space, 60)
    claim_presence = start_claim_presence(harness, 60)
    assert ordinary.ended_at is None and claim_presence.ended_at is None

    revoked = harness.staff_client.post(
        f"/api/v1/admin/makerspaces/{harness.space.pk}/member-claim-codes/{harness.claim.pk}/revoke"
    )
    next_request = harness.claim_client.get("/api/v1/auth/me")

    assert revoked.status_code == 200
    assert next_request.status_code == 401
    ordinary.refresh_from_db()
    claim_presence.refresh_from_db()
    assert ordinary.ended_at is None
    assert claim_presence.ended_at is not None
    assert claim_presence.end_reason == PresenceSession.EndReason.CLAIM_REVOKED


def test_claim_session_cannot_accept_a_waiver():
    harness = redeemed_claim("contract-waiver")
    MakerspaceWaiver.objects.create(
        makerspace=harness.space, is_active=True, version=1, body="Desk terms"
    )

    response = harness.claim_client.post(
        f"/api/v1/member/makerspaces/{harness.space.pk}/waiver/accept"
    )

    assert response.status_code == 403
    harness.membership.refresh_from_db()
    assert harness.membership.accepted_waiver_id is None
    assert harness.membership.waiver_accepted_at is None
