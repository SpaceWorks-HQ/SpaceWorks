"""Phase 10 -- the four login-method switches, and the lockouts they must refuse.

The switches themselves are the easy half. The half worth testing is the guard: turning
a method off is the dangerous direction, and the accounts it strands are exactly the ones
forgot-password cannot rescue, because they have no usable password to reset.
"""

import pytest
from django import forms
from rest_framework.test import APIClient

from apps.accounts.admin_social import PlatformLoginMethodsForm
from apps.accounts.models import DeviceGrant, PlatformLoginMethods, User
from apps.accounts.models_social import SocialIdentity, SocialProvider
from apps.makerspaces.models import Makerspace

# Reused rather than re-mocked: these carry the provider-claim and nonce plumbing a real
# social sign-in needs, and a second copy of a JWKS mock is a second place for it to rot.
from tests.accounts.test_social_auth import (
    configure_google,
    login as social_login,
    mock_claims,
    nonce,
)

pytestmark = pytest.mark.django_db

CONFIG_URL = "/api/v1/config"
LOGIN_URL = "/api/v1/auth/login"
SIGNUP_URL = "/api/v1/auth/member-sign-up"
GOOGLE_URL = "/api/v1/auth/social/google"
PHONE_START_URL = "/api/v1/auth/phone/login/start"
PASSWORD = "Safe staff password 947!"
# `attested_login` posts this exact password, so the device-login user must hold it.
DEVICE_PASSWORD = "strong-device-password"

ALL_ON = {
    "password_enabled": True,
    "social_enabled": True,
    "phone_enabled": True,
    "self_registration_enabled": True,
}


def switches(**overrides):
    PlatformLoginMethods.objects.update_or_create(pk=1, defaults={**ALL_ON, **overrides})


def form(**overrides):
    return PlatformLoginMethodsForm(data={**ALL_ON, **overrides})


def staff_user(username="switch-staff", password=PASSWORD):
    user = User.objects.create_user(
        username=username, email=f"{username}@example.test", password=password,
        access_status=User.AccessStatus.ACTIVE,
    )
    return user


# --- defaults ---------------------------------------------------------------------


def test_an_untouched_deployment_behaves_exactly_as_before():
    """No row means nothing configured, which is every method available."""
    assert not PlatformLoginMethods.objects.exists()
    user = staff_user()
    client = APIClient()

    assert client.post(
        LOGIN_URL, {"username": user.username, "password": PASSWORD}, format="json"
    ).status_code == 200
    payload = client.get(CONFIG_URL).data
    for key in ("password_login", "self_registration", "member_accounts"):
        assert key not in payload, f"{key} must stay absent while nothing is switched off"


def test_reading_the_switches_never_writes_a_row():
    """This is read on every unauthenticated login attempt."""
    APIClient().post(LOGIN_URL, {"username": "nobody", "password": "x"}, format="json")
    assert not PlatformLoginMethods.objects.exists()


# --- enforcement ------------------------------------------------------------------


def test_password_sign_in_is_refused_and_announced_when_off():
    user = staff_user()
    switches(password_enabled=False)
    client = APIClient()

    response = client.post(
        LOGIN_URL, {"username": user.username, "password": PASSWORD}, format="json"
    )
    # 403 rather than the 401 a wrong password gets: "not this way", not "not you".
    assert response.status_code == 403
    assert client.get(CONFIG_URL).data["password_login"] == {"enabled": False}


def test_social_sign_in_is_refused_and_unadvertised_when_off():
    from apps.accounts.models_oidc import OidcProvider
    from apps.accounts.models_social import PlatformSocialAuthSettings

    PlatformSocialAuthSettings.objects.update_or_create(
        pk=1, defaults={"google_web_client_id": "google-client"}
    )
    OidcProvider.objects.create(
        slug="campus", display_name="Campus", issuer="https://idp.example.test",
        jwks_url="https://idp.example.test/jwks", client_id="campus-client",
        is_enabled=True,
    )
    client = APIClient()
    assert "google" in client.get(CONFIG_URL).data["social_auth"]

    switches(social_enabled=False)

    # The switch covers the built-ins AND every configured OIDC provider: they share one
    # endpoint, so advertising either would advertise a route that 404s.
    assert "social_auth" not in client.get(CONFIG_URL).data
    response = client.post(
        GOOGLE_URL,
        {
            "id_token": "irrelevant", "nonce": "irrelevant", "surface": "staff",
            "delivery": "web", "client_platform": "web",
        },
        format="json",
    )
    assert response.status_code == 404


def test_phone_sign_in_is_refused_when_off(monkeypatch):
    monkeypatch.setattr(
        "apps.integrations.sms.sms_configured", lambda: True, raising=False
    )
    client = APIClient()
    assert client.get(CONFIG_URL).data["phone_login"] == {"enabled": True}

    switches(phone_enabled=False)

    assert "phone_login" not in client.get(CONFIG_URL).data
    assert client.post(
        PHONE_START_URL, {"phone": "+15550100200"}, format="json"
    ).status_code == 404


def test_self_registration_is_refused_generically_when_off():
    Makerspace.objects.create(name="switch-space", slug="switch-space")
    switches(self_registration_enabled=False)
    client = APIClient()

    response = client.post(
        SIGNUP_URL,
        {"display_name": "Nobody", "email": "nobody@example.test", "password": PASSWORD},
        format="json",
    )
    # The endpoint's whole contract is that it never discloses anything, so this is the
    # same generic ack the honeypot returns.
    assert response.status_code == 200
    assert not User.objects.filter(email="nobody@example.test").exists()
    assert client.get(CONFIG_URL).data["self_registration"] == {"enabled": False}


def test_password_login_stays_available_while_only_registration_is_off():
    """The two are different questions and must not be wired together."""
    user = staff_user()
    switches(self_registration_enabled=False)

    assert APIClient().post(
        LOGIN_URL, {"username": user.username, "password": PASSWORD}, format="json"
    ).status_code == 200


# --- the two switches that did not switch (parallel-sweep P1s) --------------------
#
# Both were found by a review pass with an assigned identity lens rather than by the
# nine diff-scoped rounds, because neither defect was in the diff. The shared lesson is
# that a switch which does not switch is worse than no switch at all: the operator reads
# the console, believes a door is shut, and stops thinking about it.


def test_self_registration_off_also_blocks_social_account_creation(monkeypatch):
    """`/auth/member-sign-up` was gated; the social provider path was not.

    `resolve_social_identity` creates a brand-new active user when a subject matches no
    identity and no verified local email, and the caller then issues JWTs. So with
    self-registration off, anyone holding a Google account could still mint a local one
    -- through a different endpoint than the one the switch names.
    """
    configure_google()
    mock_claims(monkeypatch)
    switches(self_registration_enabled=False)

    response = social_login(APIClient(), nonce(APIClient()).data["nonce"])

    assert response.status_code == 403
    assert response.data["code"] == "registration_disabled"
    assert not SocialIdentity.objects.exists()
    assert not User.objects.filter(email="person@example.test").exists()


def test_a_refused_social_registration_is_audited(monkeypatch):
    """The nonce is consumed before resolution can refuse, so the refusal is a state
    change and must leave a trace -- the same rule the phone confirm guard follows.
    Returning a 403 does not make an already committed `consumed_at` read-only."""
    from apps.audit.models import AuditLog

    configure_google()
    mock_claims(monkeypatch)
    switches(self_registration_enabled=False)

    refused = social_login(APIClient(), nonce(APIClient()).data["nonce"])

    assert refused.status_code == 403
    entry = AuditLog.objects.filter(action="auth.social_login_failed").first()
    assert entry is not None, "a consumed nonce with no audit row is the defect"
    assert entry.meta["reason"] == "registration_disabled"
    # The address that was refused must not be written to an append-only log.
    assert "person@example.test" not in str(entry.meta)


def test_registration_off_still_lets_an_existing_identity_sign_in(monkeypatch):
    """The gate must cover account CREATION only.

    Signing in on an already-linked identity is not registration, and breaking it would
    lock every existing social user out the moment an operator closed sign-ups.
    """
    configure_google()
    mock_claims(monkeypatch)
    existing = User.objects.create_user(
        username="already-linked", email="person@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )
    SocialIdentity.objects.create(
        user=existing, provider=SocialProvider.GOOGLE, provider_sub="google-sub"
    )
    switches(self_registration_enabled=False)

    response = social_login(APIClient(), nonce(APIClient()).data["nonce"])

    assert response.status_code == 200
    assert response.data["outcome"] != "created"
    assert SocialIdentity.objects.count() == 1


def test_password_off_also_blocks_device_login(settings, monkeypatch):
    """`DeviceLoginView` authenticated a username/password and minted a `DeviceGrant`.

    That grant carries its own rotating refresh family, so a password accepted here
    outlives the browser session the switch was believed to have closed. The refusal has
    to land before `authenticate()` runs, and it reuses the generic credential error so
    the endpoint discloses no more than it did before.
    """
    from tests.accounts.test_device_auth import attested_login

    user = staff_user("device-switch")
    user.set_password(DEVICE_PASSWORD)
    user.save(update_fields=["password"])
    switches(password_enabled=False)

    response, _payload = attested_login(APIClient(), user, settings, monkeypatch)

    assert response.status_code == 401
    assert not DeviceGrant.objects.filter(user=user).exists()


# --- the lockout guards -----------------------------------------------------------


def test_disabling_social_is_refused_when_it_is_somebodys_only_credential():
    stranded = User.objects.create_user(
        username="social-only", email="social-only@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )
    stranded.set_unusable_password()
    stranded.save()
    # Two providers: the per-provider guard in `social_lockout` would clear either one,
    # and only the platform-wide check sees that switching social off strands them.
    SocialIdentity.objects.create(
        user=stranded, provider=SocialProvider.GOOGLE, provider_sub="g-1"
    )
    SocialIdentity.objects.create(
        user=stranded, provider=SocialProvider.APPLE, provider_sub="a-1"
    )

    assert form(social_enabled=False).is_valid() is False
    assert form().is_valid() is True


def test_an_inactive_account_does_not_block_the_change():
    stranded = User.objects.create_user(
        username="gone", email="gone@example.test",
        access_status=User.AccessStatus.ACTIVE, is_active=False,
    )
    stranded.set_unusable_password()
    stranded.save()
    SocialIdentity.objects.create(
        user=stranded, provider=SocialProvider.GOOGLE, provider_sub="g-2"
    )

    assert form(social_enabled=False).is_valid() is True


def test_disabling_passwords_is_refused_when_a_superadmin_has_no_provider():
    User.objects.create_superuser(
        username="root", email="root@example.test", password=PASSWORD
    )

    assert form(password_enabled=False).is_valid() is False


def test_disabling_passwords_is_allowed_once_every_superadmin_can_use_a_provider():
    root = User.objects.create_superuser(
        username="root", email="root@example.test", password=PASSWORD
    )
    SocialIdentity.objects.create(
        user=root, provider=SocialProvider.GOOGLE, provider_sub="g-root"
    )

    assert form(password_enabled=False).is_valid() is True


def test_password_and_social_can_never_both_be_off():
    """Phone issues member sessions only, so nobody could reach /control/ again."""
    assert form(password_enabled=False, social_enabled=False).is_valid() is False


def test_the_switch_row_cannot_be_deleted_from_the_console():
    from apps.accounts.admin_social import PlatformLoginMethodsAdmin

    # Deleting it reads as "nothing configured", which is every method back on — a
    # silent reversal of a deliberate choice.
    assert PlatformLoginMethodsAdmin.has_delete_permission(
        PlatformLoginMethodsAdmin, None
    ) is False


def test_the_guard_names_the_remedy():
    """A refusal the superadmin cannot act on is a dead end."""
    User.objects.create_superuser(
        username="root", email="root@example.test", password=PASSWORD
    )
    bound = form(password_enabled=False)
    bound.is_valid()
    message = " ".join(bound.errors.get(forms.forms.NON_FIELD_ERRORS, []))
    assert "Link a provider" in message
