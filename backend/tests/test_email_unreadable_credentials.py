"""SMTP credentials that no longer decrypt (cloud lane).

`API_CLIENT_ENC_KEY` changing underneath the database leaves every stored SMTP password as
ciphertext the box cannot read. A delivery must then fail as an ordinary, classified,
retryable FAILED row -- never raise into the workflow that sent it -- and the platform
"is email configured" check must stop claiming a recovery path that cannot send.
"""

import pytest
from django.test import override_settings

from apps.integrations.dispatch import dispatch_email
from apps.integrations.email import platform_email_configured
from apps.integrations.models import EmailLog, PlatformEmailSettings
from apps.makerspaces.models import Makerspace
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db

GARBAGE = "fernet:not-a-real-token"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_an_undecryptable_makerspace_smtp_password_fails_the_row_not_the_caller(
    mailoutbox, monkeypatch
):
    monkeypatch.setattr(
        "apps.integrations.email.validate_smtp_endpoint", lambda host, port: None
    )
    space = make_space("smtp-unreadable")
    Makerspace.objects.filter(pk=space.pk).update(
        smtp_host="smtp.example.org", smtp_port=587, smtp_password=GARBAGE
    )
    space.refresh_from_db()

    log = dispatch_email(
        to_email="member@example.com", subject="Reminder", text_body="Due back",
        makerspace=space, sync=True,
    )

    assert log.status == EmailLog.Status.FAILED
    assert log.error == "email_delivery_failed:InvalidToken"
    assert GARBAGE not in log.error
    assert mailoutbox == []


def test_platform_email_with_an_unreadable_password_is_not_configured():
    row = PlatformEmailSettings.load()
    row.smtp_host = "smtp.example.org"
    row.save()
    assert platform_email_configured() is True

    PlatformEmailSettings.objects.filter(pk=row.pk).update(smtp_password=GARBAGE)

    assert platform_email_configured() is False


def test_platform_email_with_a_readable_password_stays_configured():
    row = PlatformEmailSettings.load()
    row.smtp_host = "smtp.example.org"
    row.set_smtp_password("app-password")
    row.save()

    assert platform_email_configured() is True
