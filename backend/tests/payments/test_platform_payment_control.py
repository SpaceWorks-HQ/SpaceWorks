"""Control forms protect and audit the platform payment singleton."""

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.payments.models import PlatformStripeConnectSettings
from tests.accounts.mfa_helpers import force_mfa_login
from tests.return_helpers import make_user

pytestmark = pytest.mark.django_db


def test_control_platform_credential_change_is_audited_without_secret_values(client):
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_secret_key("sk_control_old")
    platform.set_stripe_webhook_secret("whsec_control")
    platform.stripe_connect_client_id = "ca_control"
    platform.save()
    superadmin = make_user(
        "platform-control-audit-admin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_superuser=True,
        is_staff=True,
    )
    force_mfa_login(client, superadmin)

    response = client.post(
        reverse(
            "admin:payments_platformstripeconnectsettings_change",
            args=[platform.pk],
        ),
        {
            "stripe_publishable_key": "",
            "stripe_secret_key": "sk_control_rotated_must_not_leak",
            "stripe_webhook_secret": "",
            "stripe_connect_client_id": "ca_control",
            "application_fee_bps": 0,
            "_save": "Save",
        },
    )

    assert response.status_code == 302
    event = AuditLog.objects.get(
        action="platform.stripe_connect_settings_updated",
        actor=superadmin,
        target_id=str(platform.pk),
    )
    assert "stripe_secret_key" in event.meta["changed_fields"]
    assert "sk_control_rotated_must_not_leak" not in str(event.meta)


def test_control_cannot_delete_platform_connect_settings_singleton(client):
    platform = PlatformStripeConnectSettings.load()
    superadmin = make_user(
        "platform-control-delete-admin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_superuser=True,
        is_staff=True,
    )
    force_mfa_login(client, superadmin)
    delete_url = reverse(
        "admin:payments_platformstripeconnectsettings_delete",
        args=[platform.pk],
    )

    assert client.get(delete_url).status_code == 403
    assert client.post(delete_url, {"post": "yes"}).status_code == 403
    assert PlatformStripeConnectSettings.objects.filter(pk=platform.pk).exists()


