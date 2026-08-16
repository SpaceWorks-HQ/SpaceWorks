from django.utils import timezone

from apps.accounts.services_password_reset import request_password_reset
from apps.accounts.services_password_reset_drain import (
    claim_pending_envelopes,
    finalize_delivery,
    prepare_delivery,
)


def issue_otp(user, monkeypatch, *, now=None):
    """Issue through E1's real envelope state machine while retaining the test code."""
    issued_at = now or timezone.now()
    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.email_enabled", lambda: True
    )
    request_password_reset(user.email, now=issued_at)
    claim = claim_pending_envelopes(owner="endpoint-test", now=issued_at)[0]
    attempt = prepare_delivery(claim, now=issued_at)
    assert attempt is not None
    assert finalize_delivery(claim, delivered=True, now=issued_at) is True
    return attempt.code
