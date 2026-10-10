"""`/control/` edits to platform integration settings land in the audit trail (cloud lane).

The staff-console API for these rows always audited; the `/control/` forms for the very
same rows wrote only Django's `LogEntry`. A superadmin could change the SMS provider, push
credentials or a login-method switch with nothing in the append-only, attested log. The
metadata names changed fields and never a value: several are write-only secret inputs.
"""

import pytest
from django.contrib import admin as django_admin
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.models_login_methods import PlatformLoginMethods
from apps.accounts.models_oidc import OidcProvider
from apps.accounts.models_social import PlatformSocialAuthSettings
from apps.audit.models import AuditLog
from apps.integrations.models import PlatformEmailSettings
from apps.integrations.models_push import PlatformPushSettings
from apps.integrations.models_sms import PlatformSmsSettings
from apps.updates.models import PlatformUpdateSettings
from config.admin_audit import AuditedControlChangeMixin
from tests.return_helpers import make_user
from tests.accounts.mfa_helpers import force_mfa_login

pytestmark = pytest.mark.django_db

AUDITED = {
    PlatformEmailSettings: "platform.email_settings_updated",
    PlatformSmsSettings: "platform.sms_settings_updated",
    PlatformPushSettings: "platform.push_settings_updated",
    PlatformSocialAuthSettings: "platform.social_auth_settings_updated",
    PlatformLoginMethods: "platform.login_methods_updated",
    OidcProvider: "platform.oidc_provider_saved",
    PlatformUpdateSettings: "platform.update_settings_updated",
}

SECRET = "AC-super-secret-twilio-token-value"


def _superadmin_client():
    user = make_user(
        "control-audit-root", role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE, is_staff=True, is_superuser=True,
    )
    client = Client()
    force_mfa_login(client, user)
    return client, user


@pytest.mark.parametrize("model", list(AUDITED), ids=lambda m: m.__name__)
def test_every_platform_integration_admin_is_audited(model):
    model_admin = django_admin.site._registry[model]

    assert isinstance(model_admin, AuditedControlChangeMixin)
    assert model_admin.audit_action == AUDITED[model]


def test_an_sms_settings_save_is_audited_without_the_secret():
    client, root = _superadmin_client()
    row = PlatformSmsSettings.load()

    response = client.post(
        reverse("admin:integrations_platformsmssettings_change", args=[row.pk]),
        {
            "is_enabled": "on", "provider": "twilio", "account_sid": "AC123",
            "auth_token_raw": SECRET, "from_number": "+14155550100",
        },
    )

    assert response.status_code == 302, getattr(response, "context", None)
    event = AuditLog.objects.get(action="platform.sms_settings_updated")
    assert event.actor == root
    assert event.meta["via"] == "control"
    assert event.meta["created"] is False
    assert "auth_token_raw" in event.meta["changed_fields"]
    assert "is_enabled" in event.meta["changed_fields"]
    assert SECRET not in repr(event.meta)


def test_a_login_method_switch_is_audited():
    client, root = _superadmin_client()
    row = PlatformLoginMethods.load()
    row.save()

    response = client.post(
        reverse("admin:accounts_platformloginmethods_change", args=[row.pk]),
        {
            "password_enabled": "on", "social_enabled": "on",
            "self_registration_enabled": "",  # turned off
        },
    )

    assert response.status_code == 302
    event = AuditLog.objects.get(action="platform.login_methods_updated")
    assert event.actor == root
    assert "self_registration_enabled" in event.meta["changed_fields"]


def test_a_refused_form_writes_no_audit_row():
    client, _ = _superadmin_client()
    row = PlatformSmsSettings.load()

    response = client.post(
        reverse("admin:integrations_platformsmssettings_change", args=[row.pk]),
        {"provider": "twilio", "from_number": "not a phone number"},
    )

    assert response.status_code == 200  # the form re-renders with the error
    assert not AuditLog.objects.filter(action="platform.sms_settings_updated").exists()
