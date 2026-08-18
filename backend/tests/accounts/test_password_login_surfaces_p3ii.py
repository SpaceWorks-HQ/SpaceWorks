from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts import services_registration
from apps.accounts.models import User
from apps.accounts.tokens import SpaceWorksRefreshToken
from apps.makerspaces.models import Makerspace, MakerspaceMembership


pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login"
SIGNUP = "/api/v1/auth/member-sign-up"
ME = "/api/v1/auth/me"
RESEND = "/api/v1/auth/email-verification/resend"
CONFIRM = "/api/v1/auth/email-verification/confirm"
MEMBERSHIPS = "/api/v1/memberships/me"
STAFF_API = "/api/v1/admin/makerspaces"
PASSWORD = "Safe member password 947!"
ACK = {"detail": "If the details are valid, a verification email has been sent."}


def _bearer(access):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


def _signup(client, email, *, password=PASSWORD):
    return client.post(
        SIGNUP,
        {
            "display_name": "Surface Member",
            "email": email,
            "password": password,
        },
        format="json",
    )


def _verified_staff_origin(slug):
    space = Makerspace.objects.create(
        name=slug.title(),
        slug=slug,
        frontend_domain=f"{slug}.example.test",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )
    return space, f"https://{slug}.example.test"


def test_member_password_login_is_explicitly_member_and_cannot_reach_staff_api():
    user = User.objects.create_user(
        username="password-member",
        email="password-member@example.test",
        password=PASSWORD,
    )

    response = APIClient().post(
        LOGIN,
        {"username": user.email, "password": PASSWORD, "surface": "member"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["surface"] == "member"
    assert AccessToken(response.data["access"])["surface"] == "member"
    assert _bearer(response.data["access"]).get(STAFF_API).status_code == 403


def test_staff_password_login_has_authority_and_is_bound_to_trusted_origin():
    space, origin = _verified_staff_origin("password-staff")
    _other_space, other_origin = _verified_staff_origin("password-staff-other")
    user = User.objects.create_user(
        username="password-staff",
        email="password-staff@example.test",
        password=PASSWORD,
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )

    response = APIClient().post(
        LOGIN,
        {"username": user.username, "password": PASSWORD, "surface": "staff"},
        format="json",
        HTTP_ORIGIN=origin,
    )

    assert response.status_code == 200
    claims = AccessToken(response.data["access"])
    assert response.data["surface"] == claims["surface"] == "staff"
    assert claims["staff_scope"] == str(space.pk)
    client = _bearer(response.data["access"])
    assert client.get(STAFF_API, HTTP_ORIGIN=origin).status_code == 200
    assert client.get(STAFF_API, HTTP_ORIGIN=other_origin).status_code == 403


def test_legacy_surface_less_token_is_treated_as_member():
    user = User.objects.create_user(
        username="legacy-surface-less",
        email="legacy-surface-less@example.test",
        password=PASSWORD,
    )
    refresh = SpaceWorksRefreshToken.for_user(user)
    assert "surface" not in refresh

    client = _bearer(str(refresh.access_token))

    assert client.get(ME).status_code == 200
    assert client.get(STAFF_API).status_code == 403


def test_unverified_signup_session_is_verification_only_then_becomes_member(monkeypatch):
    codes = []
    monkeypatch.setattr(
        services_registration,
        "send_email_verification_otp",
        lambda _email, code: codes.append(code) or 1,
    )
    email = "verification-only@example.test"
    assert _signup(APIClient(), email).data == ACK

    login = APIClient().post(
        LOGIN,
        {"username": email, "password": PASSWORD, "surface": "member"},
        format="json",
    )
    assert login.status_code == 200
    assert login.data["surface"] == "verification_only"
    assert AccessToken(login.data["access"])["surface"] == "verification_only"
    client = _bearer(login.data["access"])

    assert client.get(ME).status_code == 200
    assert client.post(RESEND, format="json").status_code == 200
    assert client.get(MEMBERSHIPS).status_code == 403
    assert client.get(STAFF_API).status_code == 403

    confirmed = client.post(CONFIRM, {"code": codes[0]}, format="json")

    assert confirmed.status_code == 200
    assert client.get(MEMBERSHIPS).status_code == 200
    assert client.get(STAFF_API).status_code == 403


def test_stale_unverified_signup_releases_email_but_verified_account_is_untouched(
    monkeypatch,
):
    monkeypatch.setattr(
        services_registration, "send_email_verification_otp", lambda *_: 0
    )
    client = APIClient()
    released_email = "released-signup@example.test"
    verified_email = "verified-signup@example.test"
    assert _signup(client, released_email).data == ACK
    stale = User.objects.get(email=released_email)
    User.objects.filter(pk=stale.pk).update(
        self_registered_at=timezone.now()
        - services_registration.SELF_REGISTRATION_HOLD_TTL
        - timedelta(seconds=1)
    )

    takeover = _signup(client, released_email, password="Replacement password 582!")
    replacement = User.objects.get(email=released_email)
    stale.refresh_from_db()

    assert takeover.data == ACK
    assert replacement.pk != stale.pk
    assert replacement.check_password("Replacement password 582!")
    assert stale.email == "" and stale.is_active is False

    verified = User.objects.create_user(
        username="verified-self-registration",
        email=verified_email,
        password=PASSWORD,
        self_registered_at=timezone.now()
        - services_registration.SELF_REGISTRATION_HOLD_TTL
        - timedelta(days=1),
    )
    User.objects.filter(pk=verified.pk).update(email_verified_at=timezone.now())
    duplicate = _signup(client, verified_email, password="Attacker password 771!")
    verified.refresh_from_db()

    assert duplicate.data == takeover.data == ACK
    assert verified.email == verified_email and verified.is_active
    assert verified.check_password(PASSWORD)
    assert not verified.check_password("Attacker password 771!")
    assert User.objects.filter(email__iexact=verified_email).count() == 1
