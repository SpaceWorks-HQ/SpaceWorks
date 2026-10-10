"""The staff-console social-settings API refuses the same lockout the `/control/` form does.

`PlatformSocialAuthSettingsForm.clean` refuses to clear a provider that is some account's
only credential. `PATCH /api/v1/admin/platform/social-auth-settings` writes the same row and
had no such check, so the guard could be walked around from the console (cloud lane).
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.models_social import PlatformSocialAuthSettings, SocialIdentity, SocialProvider
from apps.audit.models import AuditLog
from tests.return_helpers import make_user

pytestmark = pytest.mark.django_db

URL = "/api/v1/admin/platform/social-auth-settings"


def _root():
    client = APIClient()
    client.force_authenticate(
        make_user(
            "social-lockout-root", is_superuser=True, is_staff=True,
            role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE,
        )
    )
    return client


def _social_only(username, provider=SocialProvider.GOOGLE):
    user = User.objects.create_user(username=username, email=f"{username}@example.test")
    user.set_unusable_password()
    user.save(update_fields=["password"])
    SocialIdentity.objects.create(user=user, provider=provider, provider_sub=username)
    return user


def test_clearing_a_provider_that_strands_an_account_is_refused():
    PlatformSocialAuthSettings.objects.create(pk=1, google_web_client_id="web-id")
    _social_only("api-stranded")

    response = _root().patch(URL, {"google_web_client_id": ""}, format="json")

    assert response.status_code == 400
    assert "lock out 1 account" in " ".join(response.json()["non_field_errors"])
    assert PlatformSocialAuthSettings.objects.get(pk=1).google_web_client_id == "web-id"
    assert not AuditLog.objects.filter(action="platform.social_auth_settings_updated").exists()


def test_clearing_a_provider_nobody_depends_on_is_allowed():
    PlatformSocialAuthSettings.objects.create(pk=1, google_web_client_id="web-id")
    User.objects.create_user(username="api-safe", email="safe@example.test", password="password")

    response = _root().patch(URL, {"google_web_client_id": ""}, format="json")

    assert response.status_code == 200
    assert AuditLog.objects.filter(action="platform.social_auth_settings_updated").exists()


def test_an_unrelated_edit_is_not_blocked_by_an_existing_dependency():
    PlatformSocialAuthSettings.objects.create(pk=1, google_web_client_id="web-id")
    _social_only("api-dependent")

    response = _root().patch(URL, {"apple_team_id": "TEAMID"}, format="json")

    assert response.status_code == 200


def test_a_non_superadmin_cannot_reach_the_settings():
    client = APIClient()
    client.force_authenticate(make_user("social-lockout-member", access_status=User.AccessStatus.ACTIVE))

    assert client.get(URL).status_code == 403
    assert client.patch(URL, {"google_web_client_id": ""}, format="json").status_code == 403
