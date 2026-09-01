from unittest.mock import Mock
from contextlib import nullcontext
import json

import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.test import override_settings
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.models import User
from apps.hardware_requests import notifications
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.integrations.telegram import TelegramDeliveryError, send_message
from apps.integrations.views import TelegramWebhookView
from tests.return_helpers import authenticated_client, make_accepted_request, make_member, make_product, make_space

pytestmark = pytest.mark.django_db

WEBHOOK_SECRET = "test-webhook-secret"
WEBHOOK_URL = "/api/v1/integrations/telegram/webhook"


def test_telegram_webhook_uses_dedicated_throttle_scope():
    assert TelegramWebhookView.throttle_scope == "telegram_webhook"


@override_settings(TELEGRAM_WEBHOOK_SECRET=WEBHOOK_SECRET)
def test_telegram_webhook_throttles_rapid_requests(settings, monkeypatch):
    cache.clear()
    rest_framework_settings = dict(django_settings.REST_FRAMEWORK)
    rest_framework_settings["DEFAULT_THROTTLE_RATES"] = {
        **django_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
        "telegram_webhook": "1/min",
    }
    settings.REST_FRAMEWORK = rest_framework_settings
    monkeypatch.setattr(
        ScopedRateThrottle,
        "THROTTLE_RATES",
        rest_framework_settings["DEFAULT_THROTTLE_RATES"],
    )
    client = authenticated_client(
        User.objects.create_user(
            username="telegram-throttle-placeholder",
            role=User.Role.SUPERADMIN,
            access_status=User.AccessStatus.ACTIVE,
        )
    )
    payload = {"callback_query": {"from": {"id": 999}, "data": "accept:1"}}

    first = client.post(
        WEBHOOK_URL,
        payload,
        format="json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=WEBHOOK_SECRET,
    )
    second = client.post(
        WEBHOOK_URL,
        payload,
        format="json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=WEBHOOK_SECRET,
    )

    # 200 now, not 403: the callback is acknowledged and discarded rather than
    # rejected during actor resolution, which no longer happens.
    assert first.status_code == 200
    assert second.status_code == 429


@override_settings(TELEGRAM_WEBHOOK_SECRET=WEBHOOK_SECRET)
def test_an_accept_callback_no_longer_changes_request_state(monkeypatch):
    """Chat is a notification channel, not a decision surface.

    This replaces `test_telegram_accept_callback_routes_through_workflow`. The actor
    resolution and RBAC checks it used to assert went with the route: there is nothing
    left to authorize, so the property worth pinning is that a well-formed, correctly
    secreted accept callback from a genuinely authorized admin still moves nothing.
    """
    makerspace = make_space("telegram")
    admin = make_member("telegram-admin", makerspace)
    admin.telegram_user_id = "42"
    admin.save(update_fields=["telegram_user_id"])
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)
    hardware_request.status = HardwareRequest.Status.PENDING_APPROVAL
    hardware_request.save(update_fields=["status"])
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))

    response = authenticated_client(admin).post(
        WEBHOOK_URL,
        {
            "callback_query": {
                "from": {"id": 42},
                "data": f"accept:{hardware_request.id}",
            }
        },
        format="json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=WEBHOOK_SECRET,
    )

    # 200, not 403: an already-registered webhook must be acknowledged rather than
    # retried for hours by Telegram.
    assert response.status_code == 200
    assert response.data["detail"] == "Ignored."
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.PENDING_APPROVAL


@override_settings(TELEGRAM_WEBHOOK_SECRET=WEBHOOK_SECRET)
def test_an_unlinked_telegram_actor_is_acknowledged_and_ignored():
    """Previously 403 via actor resolution. There is no actor to resolve now, and an
    unauthenticated stranger who guessed the secret still cannot make anything happen."""
    response = authenticated_client(
        User.objects.create_user(
            username="placeholder",
            role=User.Role.SUPERADMIN,
            access_status=User.AccessStatus.ACTIVE,
        )
    ).post(
        WEBHOOK_URL,
        {"callback_query": {"from": {"id": 999}, "data": "accept:1"}},
        format="json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=WEBHOOK_SECRET,
    )

    assert response.status_code == 200
    assert response.data["detail"] == "Ignored."


@override_settings(TELEGRAM_WEBHOOK_SECRET=WEBHOOK_SECRET)
def test_telegram_webhook_rejects_missing_or_wrong_secret():
    # The spoofable `from.id` must never reach the workflow without a valid secret.
    response = authenticated_client(
        User.objects.create_user(
            username="placeholder",
            role=User.Role.SUPERADMIN,
            access_status=User.AccessStatus.ACTIVE,
        )
    ).post(
        WEBHOOK_URL,
        {"callback_query": {"from": {"id": 42}, "data": "accept:1"}},
        format="json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="wrong-secret",
    )

    assert response.status_code == 403


def test_suspended_user_cannot_send_telegram_test_alert():
    makerspace = make_space("telegram-test-alert")
    admin = make_member("telegram-alert-admin", makerspace)
    admin.access_status = User.AccessStatus.SUSPENDED
    admin.save(update_fields=["access_status"])

    response = authenticated_client(admin).post(
        "/api/v1/integrations/telegram/test-alert",
        {"makerspace_id": makerspace.id, "message": "hi"},
        format="json",
    )

    assert response.status_code == 403


def test_test_alert_unconfigured_returns_delivered_false_with_detail():
    # No token/chat_id saved → send_message returns False. The endpoint must report
    # delivered:false + a "not configured" detail (HTTP 200), not an error.
    makerspace = make_space("telegram-unconfigured")
    admin = make_member("telegram-unconfigured-admin", makerspace)

    response = authenticated_client(admin).post(
        "/api/v1/integrations/telegram/test-alert",
        {"makerspace_id": makerspace.id, "message": "hi"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["delivered"] is False
    assert "configured" in response.json()["detail"].lower()


def test_test_alert_delivery_failure_returns_delivered_false_not_500(monkeypatch):
    # A real Telegram failure raises TelegramDeliveryError. The endpoint must catch it
    # and return delivered:false + detail (HTTP 200) so the staff console shows a clear
    # message instead of a generic 500.
    makerspace = make_space("telegram-delivery-failure")
    admin = make_member("telegram-failure-admin", makerspace)
    monkeypatch.setattr(
        "apps.integrations.views.send_message",
        Mock(side_effect=TelegramDeliveryError("boom")),
    )

    response = authenticated_client(admin).post(
        "/api/v1/integrations/telegram/test-alert",
        {"makerspace_id": makerspace.id, "message": "hi"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["delivered"] is False
    assert response.json()["detail"]


def test_telegram_delivery_uses_decrypted_makerspace_bot_token(monkeypatch, settings):
    settings.TELEGRAM_API_URL = "https://telegram.test"
    makerspace = make_space("telegram-encrypted-token")
    makerspace.telegram_group_chat_id = "-100123"
    makerspace.set_telegram_bot_token("bot-token")
    makerspace.save(update_fields=["telegram_group_chat_id", "telegram_bot_token"])
    posted = Mock()
    posted.return_value = nullcontext(type("Response", (), {"status": 200})())
    monkeypatch.setattr("urllib.request.urlopen", posted)

    delivered = send_message(makerspace, "hello")

    assert delivered is True
    posted.assert_called_once()
    request = posted.call_args.args[0]
    assert request.full_url == "https://telegram.test/botbot-token/sendMessage"
    assert json.loads(request.data.decode()) == {
        "chat_id": "-100123",
        "text": "hello",
    }
    assert makerspace.telegram_bot_token != "bot-token"


def test_submitted_request_telegram_alert_includes_contact_and_items(
    monkeypatch, django_capture_on_commit_callbacks
):
    makerspace = make_space("telegram-submitted-alert")
    requester = User.objects.create_user(
        username="requester-alert",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    product = make_product(makerspace, name="Bench Meter")
    second_product = make_product(makerspace, name="Logic Analyzer")
    hardware_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        requester_contact_email="requester@example.com",
        requester_contact_phone="+15551234567",
        requested_for="Robotics workshop",
        status=HardwareRequest.Status.PENDING_APPROVAL,
    )
    HardwareRequestItem.objects.create(
        request=hardware_request,
        product=product,
        requested_quantity=2,
    )
    HardwareRequestItem.objects.create(
        request=hardware_request,
        product=second_product,
        requested_quantity=3,
    )
    sent = Mock(return_value=True)
    monkeypatch.setattr("apps.integrations.dispatch_channels._channel_configured", lambda *a: True)
    monkeypatch.setattr("apps.integrations.telegram.send_message", sent)

    with django_capture_on_commit_callbacks(execute=True):
        notifications.notify_request_submitted(hardware_request)

    text = sent.call_args.args[1]
    assert "requester@example.com" in text
    assert "+15551234567" in text
    assert "Robotics workshop" in text
    assert "Bench Meter: 2" in text
    assert "Logic Analyzer: 3" in text
    assert "parse_mode" not in sent.call_args.kwargs
    # No inline keyboard: an accept/reject button IS an action surface, and chat is
    # not one any more. The alert now points staff at the console instead.
    assert "reply_markup" not in sent.call_args.kwargs
    assert "Review and decide in the staff console." in text


def test_submitted_request_telegram_delivery_error_is_swallowed(
    monkeypatch, django_capture_on_commit_callbacks
):
    makerspace = make_space("telegram-submitted-failure")
    requester = User.objects.create_user(
        username="requester-failure",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    product = make_product(makerspace)
    hardware_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.PENDING_APPROVAL,
    )
    HardwareRequestItem.objects.create(
        request=hardware_request,
        product=product,
        requested_quantity=1,
    )
    sent = Mock(side_effect=TelegramDeliveryError("delivery failed"))
    monkeypatch.setattr("apps.integrations.dispatch_channels._channel_configured", lambda *a: True)
    monkeypatch.setattr("apps.integrations.telegram.send_message", sent)

    with django_capture_on_commit_callbacks(execute=True):
        notifications.notify_request_submitted(hardware_request)

    sent.assert_called_once()


def test_submitted_request_telegram_message_stays_within_limit(
    monkeypatch, django_capture_on_commit_callbacks
):
    # A long requested_for must not push the payload past Telegram's 4096-char
    # limit, or the failed send would be swallowed and the alert lost.
    makerspace = make_space("telegram-long-message")
    requester = User.objects.create_user(
        username="requester-long",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    product = make_product(makerspace, name="Bench Meter")
    hardware_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        requested_for="x" * 9000,
        status=HardwareRequest.Status.PENDING_APPROVAL,
    )
    HardwareRequestItem.objects.create(
        request=hardware_request,
        product=product,
        requested_quantity=1,
    )
    sent = Mock(return_value=True)
    monkeypatch.setattr("apps.integrations.dispatch_channels._channel_configured", lambda *a: True)
    monkeypatch.setattr("apps.integrations.telegram.send_message", sent)

    with django_capture_on_commit_callbacks(execute=True):
        notifications.notify_request_submitted(hardware_request)

    text = sent.call_args.args[1]
    assert len(text) <= 4096
    # No inline keyboard: an accept/reject button IS an action surface, and chat is
    # not one any more. The alert now points staff at the console instead.
    assert "reply_markup" not in sent.call_args.kwargs
    assert "Review and decide in the staff console." in text


@override_settings(TELEGRAM_WEBHOOK_SECRET="")
def test_telegram_webhook_fails_closed_when_unconfigured():
    response = authenticated_client(
        User.objects.create_user(
            username="placeholder",
            role=User.Role.SUPERADMIN,
            access_status=User.AccessStatus.ACTIVE,
        )
    ).post(
        WEBHOOK_URL,
        {"callback_query": {"from": {"id": 42}, "data": "accept:1"}},
        format="json",
    )

    assert response.status_code == 403
