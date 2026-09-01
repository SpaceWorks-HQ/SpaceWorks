"""Phase 9 -- the first-run Google sign-in step.

The wizard's contract is that the step is skippable and that skipping leaves password
login working. The command is what the wizard calls; these tests pin its behaviour and
the "skip changes nothing" property the installers rely on.
"""

import pytest
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient

from apps.accounts.models_social import PlatformSocialAuthSettings

pytestmark = pytest.mark.django_db

CONFIG = "/api/v1/config"
CLIENT_ID = "1234-abc.apps.googleusercontent.com"


def test_configuring_google_publishes_it_to_the_login_screen():
    call_command("configure_social_auth", google_web_client_id=CLIENT_ID)
    body = APIClient().get(CONFIG).json()
    assert body["social_auth"]["google"] == {
        "enabled": True,
        "web_client_id": CLIENT_ID,
    }


def test_skipping_the_step_leaves_social_auth_absent():
    """The skip path: nothing is written, so the payload stays dormant."""
    assert "social_auth" not in APIClient().get(CONFIG).json()
    assert not PlatformSocialAuthSettings.objects.exists()


def test_calling_with_nothing_is_an_error_not_a_silent_noop():
    # A wizard that swallowed an empty invocation would report success while leaving
    # Google sign-in off, which is the confusing half-configured state to avoid.
    with pytest.raises(CommandError):
        call_command("configure_social_auth")


def test_setting_one_client_id_does_not_wipe_another():
    call_command("configure_social_auth", google_web_client_id=CLIENT_ID)
    call_command("configure_social_auth", google_ios_client_id="ios.apps.googleusercontent.com")
    row = PlatformSocialAuthSettings.objects.get(pk=1)
    assert row.google_web_client_id == CLIENT_ID
    assert row.google_ios_client_id == "ios.apps.googleusercontent.com"


def test_clear_removes_the_credentials():
    call_command("configure_social_auth", google_web_client_id=CLIENT_ID)
    call_command("configure_social_auth", clear=True)
    assert PlatformSocialAuthSettings.objects.get(pk=1).google_web_client_id == ""
    assert "social_auth" not in APIClient().get(CONFIG).json()


def test_whitespace_is_stripped():
    call_command("configure_social_auth", google_web_client_id=f"  {CLIENT_ID}  ")
    assert PlatformSocialAuthSettings.objects.get(pk=1).google_web_client_id == CLIENT_ID


def test_password_login_is_unaffected_by_skipping():
    """The property the installers promise: skip Google, password login still works."""
    from apps.accounts.models import User
    from tests.return_helpers import make_user

    make_user("wizard-admin", role=User.Role.SPACE_MANAGER, password="pw-strong-123")
    response = APIClient().post(
        "/api/v1/auth/login",
        {"username": "wizard-admin", "password": "pw-strong-123"},
        format="json",
    )
    assert response.status_code == 200
