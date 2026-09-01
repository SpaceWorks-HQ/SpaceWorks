import time
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from apps.accounts.tokens import SpaceWorksRefreshToken

from apps.accounts.models import PasswordResetEnvelope, PasswordResetEnvelopeStatus, User
from apps.accounts.services_password_reset import GENERIC_CONFIRM_ERROR, MAX_ATTEMPTS
from apps.accounts.services_password_reset_drain import (
    claim_pending_envelopes,
    prepare_delivery,
)
from apps.audit.models import AuditLog
from tests.accounts.password_reset_helpers import issue_otp

pytestmark = pytest.mark.django_db

FORGOT_URL = reverse("auth-forgot-password")
CONFIRM_URL = reverse("auth-reset-password")
STARTING_PASSWORD = "Starting-password-419!"
RECOVERED_PASSWORD = "Recovered-password-771!"


@pytest.fixture(autouse=True)
def recovery_available(monkeypatch):
    cache.clear()
    monkeypatch.setattr("apps.accounts.views_password.email_enabled", lambda: True)


def make_user(label, **changes):
    values = {
        "username": label,
        "email": f"{label}@example.org",
        "password": STARTING_PASSWORD,
        "access_status": User.AccessStatus.ACTIVE,
    }
    values.update(changes)
    return User.objects.create_user(**values)


def post_confirm(email, code, *, client=None, password=RECOVERED_PASSWORD):
    return (client or APIClient()).post(
        CONFIRM_URL,
        {"email": email, "code": code, "new_password": password},
        format="json",
    )


def test_request_endpoint_never_loads_an_account_or_issues_a_secret():
    user = make_user("request-no-account-read")

    with CaptureQueriesContext(connection) as captured:
        response = APIClient().post(FORGOT_URL, {"email": user.email}, format="json")

    assert response.status_code == 200
    assert not any(
        '"accounts_user"' in query["sql"] for query in captured.captured_queries
    )
    envelope = PasswordResetEnvelope.objects.get(email_normalized=user.email)
    assert envelope.status == PasswordResetEnvelopeStatus.PENDING
    assert envelope.user_id is None
    assert envelope.digest_is_live is False
    assert envelope.expires_at is None


def test_request_known_and_unknown_have_identical_work_and_overlapping_timings():
    pairs = []
    for index in range(8):
        known = make_user(f"timing-known-{index}").email
        pairs.append((known, f"timing-unknown-{index}@example.org"))

    durations = {"known": [], "unknown": []}
    response_bodies = []
    for index, (known, unknown) in enumerate(pairs):
        for branch, email in (("known", known), ("unknown", unknown)):
            started = time.perf_counter_ns()
            response = APIClient().post(
                FORGOT_URL,
                {"email": email},
                format="json",
                REMOTE_ADDR=f"198.51.{index}.{1 if branch == 'known' else 2}",
            )
            durations[branch].append(time.perf_counter_ns() - started)
            response_bodies.append((response.status_code, response.content))

    assert len(set(response_bodies)) == 1
    assert response_bodies[0][0] == 200
    envelopes = list(PasswordResetEnvelope.objects.order_by("email_normalized"))
    assert len(envelopes) == 16
    assert all(
        envelope.status == PasswordResetEnvelopeStatus.PENDING
        and envelope.user_id is None
        and envelope.digest_is_live is False
        and envelope.expires_at is None
        and envelope.attempts == 0
        for envelope in envelopes
    )
    events = list(
        AuditLog.objects.filter(action="auth.password_reset_requested").order_by("id")
    )
    assert len(events) == 16
    assert all(event.meta.get("method") == "otp" for event in events)
    assert all("email_hash" in event.meta for event in events)
    assert not any("@example.org" in str(event.meta) for event in events)

    known_window = (min(durations["known"]), max(durations["known"]))
    unknown_window = (min(durations["unknown"]), max(durations["unknown"]))
    assert max(known_window[0], unknown_window[0]) <= min(
        known_window[1], unknown_window[1]
    )


def test_request_api_fails_closed_before_validation_when_mail_is_unconfigured(monkeypatch):
    monkeypatch.setattr("apps.accounts.views_password.email_enabled", lambda: False)

    response = APIClient().post(FORGOT_URL, {"email": "not-an-email"}, format="json")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Password recovery is unavailable. Contact your makerspace staff.",
        "code": "recovery_unavailable",
    }
    assert PasswordResetEnvelope.objects.count() == 0
    assert AuditLog.objects.filter(action="auth.password_reset_requested").count() == 0


def test_request_cooldown_is_a_generic_acknowledgement_not_an_oracle():
    user = make_user("request-cooldown")
    first = APIClient().post(FORGOT_URL, {"email": user.email}, format="json")
    PasswordResetEnvelope.objects.filter(email_normalized=user.email).update(
        status=PasswordResetEnvelopeStatus.ISSUED
    )

    second = APIClient().post(FORGOT_URL, {"email": user.email}, format="json")

    assert second.status_code == 200
    assert second.content == first.content
    envelope = PasswordResetEnvelope.objects.get(email_normalized=user.email)
    assert envelope.status == PasswordResetEnvelopeStatus.ISSUED
    assert envelope.digest_is_live is False


def test_confirmation_is_not_gated_when_mail_becomes_unavailable(monkeypatch):
    user = make_user("mail-down-confirm")
    code = issue_otp(user, monkeypatch)
    monkeypatch.setattr("apps.accounts.views_password.email_enabled", lambda: False)

    response = post_confirm(user.email, code)

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.check_password(RECOVERED_PASSWORD)


def test_all_otp_failures_are_byte_identical_and_unknown_attempts_persist(monkeypatch):
    now = timezone.now()
    unknown_email = "failure-unknown@example.org"
    APIClient().post(FORGOT_URL, {"email": unknown_email}, format="json")
    cases = [(unknown_email, "000000", RECOVERED_PASSWORD)]

    wrong = make_user("failure-wrong")
    wrong_code = issue_otp(wrong, monkeypatch, now=now)
    cases.append(
        (wrong.email, "000000" if wrong_code != "000000" else "000001", "")
    )

    expired = make_user("failure-expired")
    expired_code = issue_otp(expired, monkeypatch, now=now)
    PasswordResetEnvelope.objects.filter(user=expired).update(
        expires_at=now - timedelta(seconds=1)
    )
    cases.append((expired.email, expired_code, RECOVERED_PASSWORD))

    exhausted = make_user("failure-exhausted")
    exhausted_code = issue_otp(exhausted, monkeypatch, now=now)
    PasswordResetEnvelope.objects.filter(user=exhausted).update(attempts=MAX_ATTEMPTS)
    cases.append((exhausted.email, exhausted_code, RECOVERED_PASSWORD))

    suspended = make_user("failure-suspended")
    suspended_code = issue_otp(suspended, monkeypatch, now=now)
    suspended.access_status = User.AccessStatus.SUSPENDED
    suspended.save(update_fields=["access_status"])
    cases.append((suspended.email, suspended_code, RECOVERED_PASSWORD))

    walk_in = make_user("failure-walk-in")
    walk_in_code = issue_otp(walk_in, monkeypatch, now=now)
    walk_in.is_walk_in = True
    walk_in.save(update_fields=["is_walk_in"])
    cases.append((walk_in.email, walk_in_code, RECOVERED_PASSWORD))

    changed = make_user("failure-credential-changed")
    changed_code = issue_otp(changed, monkeypatch, now=now)
    changed.set_password("Credential-changed-880!")
    changed.save(update_fields=["password"])
    cases.append((changed.email, changed_code, RECOVERED_PASSWORD))

    address_changed = make_user("failure-address-changed")
    old_email = address_changed.email
    address_changed_code = issue_otp(address_changed, monkeypatch, now=now)
    address_changed.email = "failure-address-new@example.org"
    address_changed.save(update_fields=["email"])
    cases.append((old_email, address_changed_code, RECOVERED_PASSWORD))

    results = [
        (response.status_code, response.content)
        for email, code, password in cases
        for response in [post_confirm(email, code, password=password)]
    ]
    assert len(set(results)) == 1
    assert results[0][0] == 400
    assert results[0][1] == (
        f'{{"detail":"{GENERIC_CONFIRM_ERROR}"}}'.encode()
    )
    unknown_envelope = PasswordResetEnvelope.objects.get(
        email_normalized=unknown_email
    )
    assert unknown_envelope.attempts == 1


@pytest.mark.parametrize("with_bearer", [False, True])
def test_walk_in_request_is_discarded_with_or_without_bearer(monkeypatch, with_bearer):
    user = make_user(f"walk-in-request-{with_bearer}", is_walk_in=True)
    client = _client_for(user) if with_bearer else APIClient()

    response = client.post(FORGOT_URL, {"email": user.email}, format="json")
    claim = claim_pending_envelopes(owner="walk-in-test")[0]
    outcome = prepare_delivery(claim)

    assert response.status_code == 200
    assert outcome == PasswordResetEnvelopeStatus.DISCARDED
    envelope = PasswordResetEnvelope.objects.get(email_normalized__iexact=user.email)
    assert envelope.status == PasswordResetEnvelopeStatus.DISCARDED
    assert envelope.digest_is_live is False


@pytest.mark.parametrize("with_bearer", [False, True])
def test_walk_in_confirmation_is_refused_with_or_without_bearer(monkeypatch, with_bearer):
    user = make_user(f"walk-in-confirm-{with_bearer}")
    code = issue_otp(user, monkeypatch)
    user.is_walk_in = True
    user.save(update_fields=["is_walk_in"])

    response = post_confirm(
        user.email, code, client=_client_for(user) if with_bearer else APIClient()
    )

    assert response.status_code == 400
    assert response.json() == {"detail": GENERIC_CONFIRM_ERROR}
    user.refresh_from_db()
    assert user.check_password(STARTING_PASSWORD)


def test_legacy_link_coexists_end_to_end_and_audits_method_link():
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    user = make_user("legacy-link")
    response = APIClient().post(
        CONFIRM_URL,
        {
            "uid": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": default_token_generator.make_token(user),
            "new_password": RECOVERED_PASSWORD,
        },
        format="json",
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.check_password(RECOVERED_PASSWORD)
    event = AuditLog.objects.get(
        action="user.password_reset_via_email", target_id=str(user.pk)
    )
    assert event.meta == {"method": "link"}


def _client_for(user):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {SpaceWorksRefreshToken.for_user(user).access_token}"
    )
    return client
