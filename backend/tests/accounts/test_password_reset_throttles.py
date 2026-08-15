from types import SimpleNamespace

from django.conf import settings

from apps.accounts.audit_events import fingerprint
from apps.accounts.throttles import (
    PasswordResetConfirmEmailThrottle,
    PasswordResetEmailThrottle,
)


def test_request_and_guess_budgets_are_distinct_and_never_cache_raw_email():
    email = "Person@Example.org"
    request = SimpleNamespace(data={"email": email})

    request_key = PasswordResetEmailThrottle().get_cache_key(request, None)
    confirm_key = PasswordResetConfirmEmailThrottle().get_cache_key(request, None)

    assert email.lower() not in request_key
    assert fingerprint(email) in request_key
    assert request_key != confirm_key
    assert "password_reset_email" in settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    assert (
        "password_reset_confirm_email"
        in settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    )
