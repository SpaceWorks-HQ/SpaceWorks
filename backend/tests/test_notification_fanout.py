from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.db import transaction

from apps.accounts.models import User
from apps.hardware_requests import notifications as hardware_notifications
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.integrations import notify
from apps.integrations.models import (
    EmailLog,
    NotificationChannel,
    NotificationDeliveryStatus,
)
from apps.integrations.notify import EmailDelivery, LifecyclePayload, NotificationResult
from tests.return_helpers import make_product, make_space

pytestmark = pytest.mark.django_db


def payload():
    return LifecyclePayload(
        text="Lifecycle update",
        emails=(
            EmailDelivery(
                to_email="staff@example.com",
                subject="Update",
                text_body="Lifecycle update",
            ),
        ),
    )


def enabled_channel(monkeypatch, selected):
    monkeypatch.setattr(
        notify,
        "is_notification_enabled",
        lambda makerspace, feature, channel: channel == selected,
    )


def successful_sinks(monkeypatch, emails, channels):
    def email_sink(**kwargs):
        emails.append(kwargs)
        return SimpleNamespace(status=EmailLog.Status.SENT)

    def channel_sink(**kwargs):
        # A list, because dispatch_channel now fans out to one log row per destination.
        channels.append(kwargs)
        return [SimpleNamespace(status=NotificationDeliveryStatus.SENT)]

    monkeypatch.setattr(notify, "dispatch_email", email_sink)
    monkeypatch.setattr(notify, "dispatch_channel", channel_sink)


def test_unknown_feature_and_event_are_suppressed():
    space = make_space("fanout-unknown")
    unknown_feature = notify.notify_lifecycle(
        space, feature="unknown", event="submitted", build=payload
    )
    unknown_event = notify.notify_lifecycle(
        space, feature="printing", event="unknown", build=payload
    )
    assert not unknown_feature.scheduled
    assert not unknown_event.scheduled


def test_async_registers_one_callback_and_sync_returns_counts(
    monkeypatch, django_capture_on_commit_callbacks
):
    space = make_space("fanout-sync")
    calls = []
    enabled_channel(monkeypatch, NotificationChannel.EMAIL)
    successful_sinks(monkeypatch, calls, [])
    builds = []

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        result = notify.notify_lifecycle(
            space,
            feature="printing",
            event="submitted",
            build=lambda: builds.append(True) or payload(),
        )
    assert result.scheduled is True
    assert len(callbacks) == 1
    assert builds == []
    callbacks[0]()
    assert builds == [True]
    assert len(calls) == 1

    sync_result = notify.notify_lifecycle(
        space, feature="printing", event="submitted", build=payload, sync=True
    )
    assert sync_result.scheduled is False
    assert sync_result.delivered_counts == {NotificationChannel.EMAIL: 1}


def test_rollback_drops_delivery(monkeypatch, django_capture_on_commit_callbacks):
    space = make_space("fanout-rollback")
    calls = []
    enabled_channel(monkeypatch, NotificationChannel.EMAIL)
    successful_sinks(monkeypatch, calls, [])
    with pytest.raises(RuntimeError):
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            with transaction.atomic():
                notify.notify_lifecycle(
                    space, feature="printing", event="submitted", build=payload
                )
                raise RuntimeError("rollback")
    assert callbacks == []
    assert calls == []


@pytest.mark.parametrize("selected", NotificationChannel.values)
def test_each_matrix_cell_only_dispatches_its_channel(monkeypatch, selected):
    space = make_space(f"fanout-{selected}")
    emails, channels = [], []
    enabled_channel(monkeypatch, selected)
    successful_sinks(monkeypatch, emails, channels)
    result = notify.notify_lifecycle(
        space, feature="printing", event="submitted", build=payload, sync=True
    )
    if selected == NotificationChannel.EMAIL:
        assert len(emails) == 1
        assert channels == []
    else:
        assert emails == []
        assert [call["channel"] for call in channels] == [selected]
    assert result.delivered_counts == {selected: 1}


def test_build_runs_once_for_all_enabled_channels(monkeypatch):
    space = make_space("fanout-build-once")
    monkeypatch.setattr(notify, "is_notification_enabled", lambda *args: True)
    successful_sinks(monkeypatch, [], [])
    builds = []
    notify.notify_lifecycle(
        space,
        feature="printing",
        event="submitted",
        build=lambda: builds.append(True) or payload(),
        sync=True,
    )
    assert builds == [True]


def test_raising_build_and_dispatch_never_escape(monkeypatch):
    space = make_space("fanout-fail-safe")
    monkeypatch.setattr(notify, "is_notification_enabled", lambda *args: True)
    broken_build = notify.notify_lifecycle(
        space,
        feature="printing",
        event="submitted",
        build=lambda: (_ for _ in ()).throw(RuntimeError("build failed")),
        sync=True,
    )
    assert broken_build.delivered_counts == {}

    monkeypatch.setattr(
        notify,
        "dispatch_email",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("email failed")),
    )
    monkeypatch.setattr(
        notify,
        "dispatch_channel",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("chat failed")),
    )
    result = notify.notify_lifecycle(
        space, feature="printing", event="submitted", build=payload, sync=True
    )
    # Every channel the space has enabled must be counted as failed -- derived rather
    # than listed so adding a channel does not silently narrow what this asserts.
    assert result.failed_counts == {
        NotificationChannel.EMAIL: 1,
        NotificationChannel.TELEGRAM: 1,
        NotificationChannel.SLACK: 1,
        NotificationChannel.MATTERMOST: 1,
        NotificationChannel.DISCORD: 1,
        NotificationChannel.NATIVE_PUSH: 1,
    }


def test_hardware_submitted_adapter_calls_one_fanout_and_carries_no_buttons(monkeypatch):
    space = make_space("fanout-hardware-adapter")
    requester = User.objects.create_user(username="fanout-hardware-requester")
    request = HardwareRequest.objects.create(
        makerspace=space,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.PENDING_APPROVAL,
    )
    HardwareRequestItem.objects.create(
        request=request,
        product=make_product(space),
        requested_quantity=1,
    )
    calls = []

    def capture(makerspace, **kwargs):
        calls.append((makerspace, kwargs, kwargs["build"]()))
        return NotificationResult(False, {}, {})

    monkeypatch.setattr(hardware_notifications, "notify_lifecycle", capture)
    hardware_notifications.notify_request_submitted(request)
    assert len(calls) == 1
    assert calls[0][1]["event"] == "submitted"
    # No inline keyboard any more: chat is a notification channel, not a decision
    # surface, so the adapter's whole telegram_reply_markup path was removed with the
    # callback route it fed.
    assert not hasattr(calls[0][2], "telegram_reply_markup")
    assert "Review and decide in the staff console." in calls[0][2].text

