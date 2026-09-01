"""B2-B: account-less request submission and its release-blocking abuse limits."""

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient, APIRequestFactory

from apps.accounts.audit_events import fingerprint
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.throttles import AnonymousRequestEmailThrottle
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_profiles import RECOMMENDED, profile_modules


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


def _space(slug, *, anonymous=True):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=profile_modules(RECOMMENDED),
        enabled_features=["inventory.self_checkout"],
        anonymous_requests_enabled=anonymous,
    )


def _product(space, name="Logic analyzer"):
    return InventoryProduct.objects.create(
        makerspace=space,
        name=name,
        total_quantity=100,
        available_quantity=100,
        is_public=True,
    )


def _payload(product, *, email="Ada@Example.Test"):
    return {
        "contact_name": "Ada Lovelace",
        "contact_email": email,
        "contact_phone": "+44 (0)20 1234 5678",
        "requested_for": "Bench diagnostics",
        "items": [{"product_id": product.pk, "quantity": 1}],
    }


def _submit(space, payload, key, *, ip="198.51.100.10", client=None):
    return (client or APIClient()).post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
        REMOTE_ADDR=ip,
    )


def test_anonymous_submit_requires_opt_in_and_succeeds_when_enabled():
    disabled = _space("anonymous-disabled", anonymous=False)
    disabled_response = _submit(disabled, _payload(_product(disabled)), "disabled")

    assert disabled_response.status_code == 401
    assert str(disabled_response.data["detail"]) == "Authentication credentials were not provided."
    assert not HardwareRequest.objects.filter(makerspace=disabled).exists()

    enabled = _space("anonymous-enabled")
    enabled_response = _submit(enabled, _payload(_product(enabled)), "enabled")

    assert enabled_response.status_code == 201, enabled_response.data
    row = HardwareRequest.objects.get(makerspace=enabled)
    # The view resolves its own Makerspace instance, so the principal is created
    # against that row; this local copy predates it.
    enabled.refresh_from_db()
    assert row.requester == enabled.anonymous_requester
    assert row.requester_username == ""
    assert row.requester_name == "Ada Lovelace"
    assert row.requester_contact_email == "ada@example.test"
    assert row.requester_contact_verified is False


def test_authenticated_submit_ignores_contact_spoofing_and_keeps_account_identity():
    space = _space("authenticated-submit", anonymous=False)
    product = _product(space)
    user = User.objects.create_user(
        username="real-account",
        display_name="Real Account",
        email="REAL@EXAMPLE.TEST",
        phone="trusted phone",
    )
    client = APIClient()
    client.force_authenticate(user)
    payload = _payload(product)
    payload.update(
        {
            "contact_name": "x" * 201,
            "contact_email": "not-an-email",
            "contact_phone": "x" * 33,
        }
    )

    response = _submit(space, payload, "ignored-for-auth", client=client)

    assert response.status_code == 201, response.data
    row = HardwareRequest.objects.get(makerspace=space)
    assert row.requester == user
    assert row.requester_username == user.username
    assert row.requester_name == user.display_name
    assert row.requester_contact_email == user.email
    assert row.requester_contact_phone == user.phone
    assert row.requester_contact_verified is True
    assert AuditLog.objects.get(action="request.submitted").actor == user


def test_anonymous_per_ip_burst_throttle_fires():
    space = _space("anonymous-ip-burst")
    product = _product(space)

    responses = [
        _submit(
            space,
            _payload(product, email=f"person{index}@example.test"),
            f"ip-burst-{index}",
        )
        for index in range(3)
    ]

    assert [response.status_code for response in responses] == [201, 201, 429]


def test_anonymous_per_ip_hour_throttle_fires(monkeypatch):
    from apps.hardware_requests.throttles import (
        AnonymousRequestIpBurstThrottle,
        AnonymousRequestIpHourThrottle,
    )

    monkeypatch.setattr(AnonymousRequestIpBurstThrottle, "rate", "100/min", raising=False)
    monkeypatch.setattr(AnonymousRequestIpHourThrottle, "rate", "2/hour", raising=False)
    space = _space("anonymous-ip-hour")
    product = _product(space)

    responses = [
        _submit(
            space,
            _payload(product, email=f"hour{index}@example.test"),
            f"ip-hour-{index}",
        )
        for index in range(3)
    ]

    assert [response.status_code for response in responses] == [201, 201, 429]


def test_anonymous_per_email_throttle_uses_only_a_fingerprint():
    space = _space("anonymous-email-limit")
    product = _product(space)
    email = "Target@Example.Test"
    responses = [
        _submit(
            space,
            _payload(product, email=email),
            f"email-{index}",
            ip=f"198.51.100.{index + 1}",
        )
        for index in range(4)
    ]

    assert [response.status_code for response in responses] == [201, 201, 201, 429]

    request = APIRequestFactory().post("/", {}, format="json")
    request.anonymous_contact_email = email.lower()
    key = AnonymousRequestEmailThrottle().get_cache_key(request, object())
    assert email.lower() not in key
    assert fingerprint(email) in key


def test_anonymous_audit_is_unattributed_and_principal_is_not_snapshotted():
    space = _space("anonymous-attribution")
    response = _submit(space, _payload(_product(space)), "attribution")

    assert response.status_code == 201, response.data
    row = HardwareRequest.objects.get(makerspace=space)
    space.refresh_from_db()
    assert row.requester == space.anonymous_requester
    assert row.requester_username == ""
    assert space.anonymous_requester.username not in {
        row.requester_username,
        row.requester_name,
        row.requester_contact_email,
        row.requester_contact_phone,
    }
    assert AuditLog.objects.get(action="request.submitted", target_id=str(row.pk)).actor is None


def test_unverified_anonymous_contact_never_receives_lifecycle_mail(monkeypatch):
    from apps.hardware_requests import notifications

    space = _space("anonymous-no-requester-mail")
    response = _submit(space, _payload(_product(space)), "no-requester-mail")
    assert response.status_code == 201, response.data
    row = HardwareRequest.objects.get(makerspace=space)
    monkeypatch.setattr(notifications, "staff_emails_for_feature", lambda *args, **kwargs: [])

    def unexpected_requester_render(*args, **kwargs):
        raise AssertionError("unverified requester mail must not be rendered")

    monkeypatch.setattr(notifications, "render_email", unexpected_requester_render)
    assert notifications._email_deliveries(row, "request_received", "submitted") == ()


def test_anonymous_idempotent_double_submit_creates_one_request_and_one_audit():
    space = _space("anonymous-idempotent")
    payload = _payload(_product(space))

    first = _submit(space, payload, "same-retry-key")
    second = _submit(space, payload, "same-retry-key")

    assert first.status_code == second.status_code == 201
    assert first.data == second.data
    assert HardwareRequest.objects.filter(makerspace=space).count() == 1
    assert AuditLog.objects.filter(action="request.submitted", makerspace=space).count() == 1


def test_reused_idempotency_key_with_different_payload_is_a_typed_conflict():
    space = _space("anonymous-idempotency-conflict")
    product = _product(space)
    first = _submit(space, _payload(product), "reused-key")
    changed = _payload(product)
    changed["requested_for"] = "A different purpose"
    second = _submit(space, changed, "reused-key")

    assert first.status_code == 201, first.data
    assert second.status_code == 409
    assert second.data["code"] == "anonymous_request_idempotency_conflict"
    assert HardwareRequest.objects.filter(makerspace=space).count() == 1


def test_outstanding_anonymous_ceiling_returns_typed_error(settings):
    settings.ANONYMOUS_REQUEST_OUTSTANDING_LIMIT = 1
    space = _space("anonymous-capacity")
    product = _product(space)

    first = _submit(space, _payload(product), "capacity-first")
    second = _submit(
        space,
        _payload(product, email="grace@example.test"),
        "capacity-second",
    )

    assert first.status_code == 201, first.data
    assert second.status_code == 429
    assert second.data["code"] == "anonymous_request_outstanding_limit"
    assert HardwareRequest.objects.filter(makerspace=space).count() == 1


def test_the_refusal_path_is_throttled_not_just_the_accepted_one():
    """An unopted-in space must not serve an UNBOUNDED 401.

    The throttles used to be selected inside `post()`, which runs *after* the
    `anonymous_requests_allowed` refusal -- so every makerspace that had not opted in
    (the default) answered unauthenticated POSTs forever, each one still paying for a
    makerspace lookup. They are declared in `throttle_classes` now, so DRF charges the
    IP budget in `initial()`, before the handler and before that refusal.
    """
    disabled = _space("anonymous-refusal-throttled", anonymous=False)
    payload = _payload(_product(disabled))

    statuses = [
        _submit(disabled, payload, f"refusal-{index}", ip="203.0.113.77").status_code
        for index in range(3)
    ]

    # 2/min burst: the first two are refused for being account-less, the third for
    # exhausting the budget. Before the fix this was [401, 401, 401].
    assert statuses[:2] == [401, 401]
    assert statuses[2] == 429
