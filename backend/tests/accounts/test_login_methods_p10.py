"""Phase 10 -- the four login-method switches, and the lockouts they must refuse.

The switches themselves are the easy half. The half worth testing is the guard: turning
a method off is the dangerous direction, and the accounts it strands are exactly the ones
forgot-password cannot rescue, because they have no usable password to reset.
"""

import pytest
from django import forms
from rest_framework.test import APIClient

from apps.accounts.admin_social import PlatformLoginMethodsForm
from apps.accounts.models import PlatformLoginMethods, User
from apps.accounts.models_social import SocialIdentity, SocialProvider
from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db

CONFIG_URL = "/api/v1/config"
LOGIN_URL = "/api/v1/auth/login"
SIGNUP_URL = "/api/v1/auth/member-sign-up"
GOOGLE_URL = "/api/v1/auth/social/google"
PHONE_START_URL = "/api/v1/auth/phone/login/start"
PASSWORD = "Safe staff password 947!"

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
