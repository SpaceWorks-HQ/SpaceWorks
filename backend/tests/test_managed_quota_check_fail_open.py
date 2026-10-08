"""A broken managed-quota lookup must fail OPEN, as both call sites already intend.

`dispatch_email` and `reserve_notification_quota` each wrap their daily-cap check in an
`except Exception: log and carry on` -- a fair-use counter that cannot be read is not a
reason to stop mail. Both had a hole in front of that handler:

* `dispatch_email` imported `PiiWriteFenced` *inside* the `try`, so any failure raised
  before the import (the `resource_limit` lookup itself) reached `except PiiWriteFenced`
  with the name still unbound -- `UnboundLocalError`, not a logged fallback.
* `reserve_notification_quota` called `resource_limit` *outside* its `try`, so the same
  failure escaped and the whole channel fan-out dropped without a log row.

`resource_limit` raises for real on a malformed `resource_limit_overrides` value
(`int("abc")`), which `/control/` can store without the staff serializer's validation.
"""

import pytest
from django.test import override_settings

from apps.integrations.dispatch import dispatch_email
from apps.integrations.models import EmailLog
from apps.makerspaces import limits
from apps.makerspaces.limits_reservations import reserve_notification_quota
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db

MANAGED = {
    "PLATFORM_DOMAIN_SUFFIX": ".space-works.tech",
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
}


def _malformed_override(slug):
    space = make_space(slug)
    space.resource_limit_overrides = {"email": "abc", "slack": "abc"}
    space.save(update_fields=["resource_limit_overrides"])
    return space


@override_settings(**MANAGED)
def test_the_override_really_is_unreadable():
    space = _malformed_override("quota-unreadable")
    with pytest.raises(ValueError):
        limits.resource_limit(space, "email")


@override_settings(**MANAGED)
def test_dispatch_email_sends_when_the_quota_lookup_raises(mailoutbox, caplog):
    space = _malformed_override("quota-email-open")

    log = dispatch_email(
        to_email="recipient@example.com",
        subject="Still delivered",
        text_body="The fair-use counter is unreadable.",
        makerspace=space,
        sync=True,
    )

    assert log.status == EmailLog.Status.SENT
    assert len(mailoutbox) == 1
    assert "daily_email_limit_check_failed" in caplog.text


@override_settings(**MANAGED)
def test_notification_quota_fails_open_when_the_lookup_raises(caplog):
    space = _malformed_override("quota-chat-open")

    assert reserve_notification_quota(space, "slack") is True
    assert "notification_limit_check_failed" in caplog.text
