from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections

from apps.accounts.models import PasswordResetEnvelope, PasswordResetEnvelopeStatus, User
from apps.accounts.services_password_reset import request_password_reset
from apps.accounts.services_password_reset_drain import drain_password_reset_envelopes

pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_first_requests_create_one_envelope_and_one_usable_code(monkeypatch):
    email = "concurrent-reset@example.org"
    User.objects.create_user(
        username="concurrent-reset",
        email=email,
        password="starting-password-419!",
        role=User.Role.REQUESTER,
    )
    gate = Barrier(2)

    def request_from_thread(spelling):
        close_old_connections()
        try:
            gate.wait(timeout=5)
            return request_password_reset(spelling).pk
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(
            pool.map(
                request_from_thread,
                ["Concurrent-Reset@example.org", " concurrent-reset@EXAMPLE.ORG "],
            )
        )

    assert len(set(ids)) == 1
    assert PasswordResetEnvelope.objects.count() == 1
    envelope = PasswordResetEnvelope.objects.get()
    assert envelope.status == PasswordResetEnvelopeStatus.PENDING

    sent = []
    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.email_enabled", lambda: True
    )
    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.send_password_reset_otp",
        lambda recipient, code, **kwargs: sent.append(code) or 1,
    )

    drain_password_reset_envelopes(owner="one-worker")
    envelope.refresh_from_db()

    assert len(sent) == 1
    assert sent[0].isdigit() and len(sent[0]) == 6
    assert envelope.status == PasswordResetEnvelopeStatus.ISSUED
    assert envelope.digest_is_live is True
