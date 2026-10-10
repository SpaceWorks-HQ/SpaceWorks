"""The remaining accounts/identity audit rows; no new login-adoption policy."""
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import PlatformLoginMethods
from apps.accounts.models_social import PlatformSocialAuthSettings
from apps.makerspaces.models import MakerspaceMembership
from tests.accounts.test_phone_auth_p8 import sms_on, verified_member, code_from, NUMBER
from tests.accounts.test_social_auth import configure_google, nonce, login, mock_claims
from tests.makerspaces.test_import_adoption import pending
from tests.makerspaces.test_membership_j1 import space, user

pytestmark = pytest.mark.django_db


def test_verified_social_login_adopts_imported_membership(monkeypatch):
    configure_google()
    makerspace = space("social-import-adoption")
    person = user("social-import-adoption-member")
    imported = pending(makerspace, person)
    mock_claims(monkeypatch, email=person.email, sub="social-adoption")
    client = APIClient()
    response = nonce(client)
    assert response.status_code == 200
    signed_in = login(client, response.data["nonce"])
    assert signed_in.status_code == 200, signed_in.data
    row = MakerspaceMembership.objects.get(makerspace=makerspace, user=person)
    assert row.status == "active" and row.assigned_role.slug == "member"
    imported.refresh_from_db()
    assert imported.adopted_at is not None


def test_apple_member_login_is_gated_when_member_accounts_are_off():
    from tests.accounts.test_member_identity_p9 import accounts_off

    # Use the same platform helper as the existing Google test, avoiding an
    # unconfigured-provider 404 that would make this guard test meaningless.
    row = PlatformSocialAuthSettings.load()
    row.apple_service_id = "apple-web-test"; row.save()
    accounts_off(space("apple-account-off"))
    response = APIClient().post("/api/v1/auth/social/apple", {
        "id_token": "token", "nonce": "unused", "surface": "member", "delivery": "web", "client_platform": "web",
    }, format="json", HTTP_ORIGIN="http://localhost:5173")
    assert response.status_code == 404 and response.data["code"] == "social_unavailable"


def test_phone_login_switch_is_rechecked_after_a_valid_code_is_issued(sms_on):
    verified_member("phone-confirm-switch")
    client = APIClient()
    assert client.post("/api/v1/auth/phone/login/start", {"phone": NUMBER}, format="json").status_code == 200
    code = code_from(sms_on)
    switches = PlatformLoginMethods.load(); switches.phone_enabled = False; switches.save()
    cache.clear()
    response = client.post("/api/v1/auth/phone/login/confirm", {"phone": NUMBER, "code": code}, format="json")
    assert response.status_code == 404
    assert "access" not in response.data
