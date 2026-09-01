import re
from datetime import timedelta

import pytest
from django.core.mail import EmailMultiAlternatives
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import PasswordResetEnvelope, PasswordResetEnvelopeStatus, User
from apps.accounts.services_password_reset import request_password_reset
from apps.accounts.services_password_reset_drain import (
    CLAIM_LEASE,
    claim_pending_envelopes,
    drain_password_reset_envelopes,
    expire_delivery_leases,
    prepare_delivery,
)
from apps.integrations.models import EmailLog

pytestmark = pytest.mark.django_db

EMAIL = "drain-member@example.org"


def member(username="drain-member", **changes):
    values = {
        "email": EMAIL,
        "password": "starting-password-419!",
        "role": User.Role.REQUESTER,
    }
    values.update(changes)
    return User.objects.create_user(username=username, **values)


def enable_mail(monkeypatch, sender):
    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.email_enabled", lambda: True
    )
    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.send_password_reset_otp", sender
    )


def test_one_claim_is_delivered_at_most_once(monkeypatch):
    member()
    sent = []

    def capture(recipient, code, **kwargs):
        sent.append((recipient, code, kwargs))
        return 1

    enable_mail(monkeypatch, capture)
    request_password_reset(EMAIL)

    first = drain_password_reset_envelopes(owner="worker-a")
    second = drain_password_reset_envelopes(owner="worker-b")

    assert first["issued"] == 1
    assert second["claimed"] == 0
    assert len(sent) == 1
    envelope = PasswordResetEnvelope.objects.get()
    assert envelope.status == PasswordResetEnvelopeStatus.ISSUED


def test_crash_after_digest_commit_never_mints_or_sends_a_second_code(monkeypatch):
    member()
    sent = []
    enable_mail(monkeypatch, lambda recipient, code, **kwargs: sent.append(code) or 1)
    request_password_reset(EMAIL)
    envelope_claim = claim_pending_envelopes(owner="crashed-worker")[0]
    attempt = prepare_delivery(envelope_claim)
    envelope = PasswordResetEnvelope.objects.get()
    committed_digest = envelope.digest

    # The process disappears here: SMTP was never entered and finalization never ran.
    assert attempt.code not in sent
    assert envelope.status == PasswordResetEnvelopeStatus.DELIVERING
    assert drain_password_reset_envelopes(owner="replacement")["claimed"] == 0
    envelope.refresh_from_db()
    assert envelope.digest == committed_digest
    assert sent == []

    expire_delivery_leases(now=envelope.claim_expires_at + timedelta(seconds=1))
    envelope.refresh_from_db()
    assert envelope.status == PasswordResetEnvelopeStatus.DELIVERY_UNKNOWN
    assert envelope.digest != committed_digest
    assert envelope.digest_is_live is False


def test_mail_unconfigured_at_issuance_mints_nothing(monkeypatch):
    member()
    request_password_reset(EMAIL)
    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.email_enabled", lambda: False
    )

    def should_not_mint():
        raise AssertionError("OTP generation must occur after the availability check")

    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.generate_otp", should_not_mint
    )
    before = PasswordResetEnvelope.objects.get().digest

    outcome = drain_password_reset_envelopes(owner="worker")
    envelope = PasswordResetEnvelope.objects.get()

    assert outcome["terminal"] == 1
    assert envelope.status == PasswordResetEnvelopeStatus.UNDELIVERABLE
    assert envelope.digest_is_live is False
    assert envelope.digest != before
    assert envelope.expires_at is None
    assert envelope.credential_fingerprint == ""


@pytest.mark.parametrize("kind", ["unknown", "inactive", "suspended", "walk_in"])
def test_unrecoverable_account_is_discarded_without_mail(monkeypatch, kind):
    if kind != "unknown":
        changes = {}
        if kind == "inactive":
            changes["is_active"] = False
        elif kind == "suspended":
            changes["access_status"] = User.AccessStatus.SUSPENDED
        else:
            changes["is_walk_in"] = True
        member(**changes)
    sent = []
    enable_mail(monkeypatch, lambda recipient, code, **kwargs: sent.append(code) or 1)
    request_password_reset(EMAIL)

    drain_password_reset_envelopes(owner="worker")
    envelope = PasswordResetEnvelope.objects.get()

    assert envelope.status == PasswordResetEnvelopeStatus.DISCARDED
    assert envelope.digest_is_live is False
    assert envelope.terminal_at is not None
    assert sent == []


def test_smtp_rejection_clears_the_committed_digest(monkeypatch):
    member()
    enable_mail(monkeypatch, lambda recipient, code, **kwargs: 0)
    request_password_reset(EMAIL)

    drain_password_reset_envelopes(owner="worker")
    envelope = PasswordResetEnvelope.objects.get()

    assert envelope.status == PasswordResetEnvelopeStatus.UNDELIVERABLE
    assert envelope.digest_is_live is False
    assert envelope.credential_fingerprint == ""
    assert envelope.expires_at is None
    assert envelope.terminal_at is not None


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEBUG=True,
)
def test_otp_is_delivered_but_never_persisted_in_email_log(mailoutbox, monkeypatch):
    # The production PostgreSQL trigger remains active in the required suite. This
    # patch only lets the repository's SQLite smoke mode exercise dispatch, where the
    # trigger function does not exist.
    monkeypatch.setattr(
        "apps.encryption.write_fence.assert_mapped_write_allowed", lambda scope: None
    )
    member()
    request_password_reset(EMAIL)

    drain_password_reset_envelopes(owner="worker")

    assert len(mailoutbox) == 1
    code = re.search(r"\b(\d{6})\b", mailoutbox[0].body).group(1)
    log = EmailLog.objects.get()
    assert log.status == EmailLog.Status.SENT
    assert log.makerspace_id is None
    assert log.connection_kind == "platform"
    assert log.text_body == ""
    assert log.html_body == ""
    assert code not in log.text_body


def test_ordinary_smtp_exception_is_terminal_and_does_not_escape(monkeypatch):
    member()

    def reject(self):
        raise RuntimeError("smtp rejected")

    monkeypatch.setattr(EmailMultiAlternatives, "send", reject)
    monkeypatch.setattr(
        "apps.accounts.services_password_reset_drain.email_enabled", lambda: True
    )
    request_password_reset(EMAIL)

    drain_password_reset_envelopes(owner="worker")

    envelope = PasswordResetEnvelope.objects.get()
    assert envelope.status == PasswordResetEnvelopeStatus.UNDELIVERABLE
