from unittest.mock import Mock

import pytest
from django.db import transaction
from django.urls import reverse

from apps.apiclients.models import ApiKeyRequest
from apps.apiclients.notifications import notify_api_key_request_resolved
from apps.audit.models import AuditLog
from apps.integrations import notify, telegram
from apps.integrations.models import (
    EmailLog, NotificationDeliveryLog, NotificationDestination,
    NotificationPreference,
)
from apps.integrations.notification_catalog import DEFAULT_CHANNEL_STATE, FEATURE_EVENTS
from apps.integrations.notification_enums import NotificationChannel, NotificationFeature
from apps.makerspaces import limits
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db
FEATURE = NotificationFeature.API_ACCESS
EVENT = "api_key_request_resolved"


def resolved_request(status="approved"):
    space = make_space("api-resolution")
    space.set_telegram_bot_token("private-bot-token")
    space.telegram_group_chat_id = "-100123"
    space.save(update_fields=["telegram_bot_token", "telegram_group_chat_id"])
    return ApiKeyRequest.objects.create(
        makerspace=space, requester=make_user("api-resolution-user"), label="ERP",
        status=status, resolution_note="Private requester note",
    )


def mute_email(space):
    NotificationPreference.objects.create(
        makerspace=space, feature=FEATURE, channel="email", enabled=False,
    )


@pytest.mark.parametrize("status", ["approved", "rejected"])
def test_resolution_uses_matrix_destinations_and_quota_without_private_chat_content(monkeypatch, status):
    row = resolved_request(status)
    destinations = [NotificationDestination.objects.create(
        makerspace=row.makerspace, channel="telegram", label=label,
        telegram_chat_id=chat_id,
    ) for label, chat_id in [("Ops", "-200"), ("Front desk", "-300")]]
    email = Mock(return_value=Mock(status=EmailLog.Status.SENT))
    send = Mock(return_value=True)
    reserve = Mock(return_value=True)
    monkeypatch.setattr(notify, "dispatch_email", email)
    monkeypatch.setattr(telegram, "send_message", send)
    monkeypatch.setattr(limits, "reserve_notification_quota", reserve)

    result = notify_api_key_request_resolved(row, sync=True)

    assert result.delivered_counts == {"email": 1, "telegram": 2}
    assert {call.kwargs["destination"].pk for call in send.call_args_list} == {d.pk for d in destinations}
    assert reserve.call_count == 2
    email.assert_called_once()
    assert email.call_args.kwargs["to_email"] == row.requester.email
    assert row.resolution_note in email.call_args.kwargs["text_body"]
    for call in send.call_args_list:
        assert call.args[0] == row.makerspace
        assert status in call.args[1]
        assert row.requester.email not in call.args[1]
        assert row.resolution_note not in call.args[1]
        assert "private-bot-token" not in call.args[1]
    logs = list(NotificationDeliveryLog.objects.filter(makerspace=row.makerspace))
    assert len(logs) == 2
    assert all(log.event == EVENT and log.feature == FEATURE for log in logs)
    assert all(log.payload["api_key_request_id"] == row.pk for log in logs)


def test_resolution_channel_mutes_stop_both_email_and_telegram(monkeypatch):
    row = resolved_request()
    for channel in ("email", "telegram"):
        NotificationPreference.objects.create(
            makerspace=row.makerspace, feature=FEATURE, channel=channel, enabled=False,
        )
    email, send, reserve = Mock(), Mock(), Mock()
    monkeypatch.setattr(notify, "dispatch_email", email)
    monkeypatch.setattr(telegram, "send_message", send)
    monkeypatch.setattr(limits, "reserve_notification_quota", reserve)
    result = notify_api_key_request_resolved(row, sync=True)
    assert result.delivered_counts == result.failed_counts == {}
    email.assert_not_called()
    send.assert_not_called()
    reserve.assert_not_called()
    assert not NotificationDeliveryLog.objects.exists()


@pytest.mark.parametrize("blocked", ["module", "quota"])
def test_resolution_obeys_module_and_quota_blocks(monkeypatch, blocked):
    row = resolved_request()
    mute_email(row.makerspace)
    if blocked == "module":
        disable_module(row.makerspace, "telegram")
        row.makerspace.refresh_from_db()
    reserve, send = Mock(return_value=False), Mock(return_value=True)
    monkeypatch.setattr(limits, "reserve_notification_quota", reserve)
    monkeypatch.setattr(telegram, "send_message", send)
    result = notify_api_key_request_resolved(row, sync=True)
    log = NotificationDeliveryLog.objects.get()
    assert log.status == ("skipped" if blocked == "module" else "failed")
    assert result.delivered_counts == {}
    send.assert_not_called()
    assert reserve.call_count == (0 if blocked == "module" else 1)


def test_staff_master_mute_keeps_requester_email_but_stops_rooms(monkeypatch):
    row = resolved_request()
    row.makerspace.staff_notifications_enabled = False
    row.makerspace.save(update_fields=["staff_notifications_enabled"])
    email, send = Mock(return_value=Mock(status=EmailLog.Status.SENT)), Mock()
    monkeypatch.setattr(notify, "dispatch_email", email)
    monkeypatch.setattr(telegram, "send_message", send)
    result = notify_api_key_request_resolved(row, sync=True)
    assert result.delivered_counts == {"email": 1}
    email.assert_called_once()
    send.assert_not_called()


def test_resolution_provider_failure_is_logged_and_does_not_escape(monkeypatch, caplog):
    row = resolved_request()
    mute_email(row.makerspace)
    monkeypatch.setattr(telegram, "send_message", Mock(side_effect=RuntimeError("private-bot-token")))
    result = notify_api_key_request_resolved(row, sync=True)
    log = NotificationDeliveryLog.objects.get()
    assert result.failed_counts == {"telegram": 1}
    assert log.status == "failed"
    assert "private-bot-token" not in log.error + caplog.text


def test_resolution_rollback_sends_nothing(monkeypatch, django_capture_on_commit_callbacks):
    row = resolved_request()
    send, email = Mock(), Mock()
    monkeypatch.setattr(telegram, "send_message", send)
    monkeypatch.setattr(notify, "dispatch_email", email)
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                notify_api_key_request_resolved(row)
                raise RuntimeError("rollback")
    assert callbacks == []
    email.assert_not_called()
    send.assert_not_called()


def test_api_access_catalog_preserves_defaults_and_can_be_muted_via_scoped_api():
    space = make_space("api-resolution-rules")
    actor = make_member("api-resolution-manager", space)
    assert FEATURE_EVENTS[FEATURE] == (EVENT,)
    assert DEFAULT_CHANNEL_STATE[FEATURE] == {
        channel: channel in {"email", "telegram"} for channel in NotificationChannel.values
    }
    url = reverse("admin-notification-rules", kwargs={"makerspace_id": space.pk})
    response = authenticated_client(actor).patch(url, {
        "preferences": [{"feature": FEATURE, "channel": "telegram", "enabled": False}],
    }, format="json")
    assert response.status_code == 200
    assert NotificationPreference.objects.get(makerspace=space, feature=FEATURE).enabled is False
    assert AuditLog.objects.filter(makerspace=space, action="notification.preferences_updated").exists()
    other = make_member("api-resolution-other", make_space("api-resolution-other"))
    assert authenticated_client(other).patch(url, {
        "preferences": [{"feature": FEATURE, "channel": "telegram", "enabled": True}],
    }, format="json").status_code == 404
