"""Off-state contracts for the notification inbox and outbound channels."""

from unittest.mock import Mock

import pytest
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.boxes.models import Box
from apps.evidence.storage import EvidenceValidationResult
from apps.hardware_requests.models import HardwareRequest
from apps.integrations.dispatch import dispatch_email
from apps.integrations.dispatch_channels import dispatch_channel
from apps.integrations.models import (
    EmailLog,
    NotificationChannel,
    NotificationDeliveryLog,
    NotificationDeliveryStatus,
    NotificationFeature,
    NotificationPreference,
)
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import core_module_keys
from apps.notifications.emit import emit_notification
from apps.notifications.models import Notification
from tests.return_helpers import make_issue_evidence, make_return_evidence, return_payload

pytestmark = pytest.mark.django_db

CORE = sorted(core_module_keys())
MODULE_KEYS = frozenset({"notifications", "email", "telegram", "slack", "discord", "mattermost"})
CHAT_CHANNELS = ("telegram", "slack", "discord", "mattermost")


def space(slug, *extra_modules):
    return Makerspace.objects.create(
        name=slug, slug=slug, enabled_modules=[*CORE, *extra_modules],
        public_inventory_enabled=True,
    )


def active_user(username, **overrides):
    values = {
        "email": f"{username}@example.test",
        "display_name": username,
        "access_status": User.AccessStatus.ACTIVE,
    }
    values.update(overrides)
    return User.objects.create_user(username=username, **values)


def client_for(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def staff_user(slug):
    return active_user(
        f"{slug}-staff",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
    )


def enable_only_notification_module(makerspace, module):
    makerspace.enabled_modules = [*CORE, module]
    makerspace.save(update_fields=["enabled_modules"])


def channel_dispatch(makerspace, channel):
    return dispatch_channel(
        makerspace=makerspace,
        channel=channel,
        feature=NotificationFeature.HARDWARE_REQUESTS,
        event="submitted",
        text_body="A request was submitted.",
        sync=True,
    )[0]


def email_dispatch(makerspace, event="submitted"):
    return dispatch_email(
        makerspace=makerspace,
        to_email="recipient@example.test",
        subject="Request submitted",
        text_body="A request was submitted.",
        stream="hardware",
        event=event,
        audience="staff",
        sync=True,
    )


def test_notifications_off_refuses_the_inbox_and_on_alone_exposes_emitted_rows(
    django_capture_on_commit_callbacks,
):
    """The inbox is a real API surface, while its emitter is a fail-safe no-op off."""
    makerspace = space("offstate-inbox")
    staff = staff_user("offstate-inbox")
    client = client_for(staff)
    url = reverse("notifications:notifications-list", args=[makerspace.pk])

    with django_capture_on_commit_callbacks(execute=True):
        emit_notification(makerspace, title="Suppressed", event="request.submitted")
    refused = client.get(url)

    assert refused.status_code == 400
    assert "notifications is disabled" in str(refused.data)
    assert not Notification.objects.filter(makerspace=makerspace).exists()

    enable_only_notification_module(makerspace, "notifications")
    with django_capture_on_commit_callbacks(execute=True):
        emit_notification(makerspace, title="Visible", event="request.submitted")
    allowed = client.get(url)

    assert allowed.status_code == 200
    assert allowed.data["count"] == 1
    assert allowed.data["results"][0]["title"] == "Visible"
    assert set(makerspace.enabled_modules) & MODULE_KEYS == {"notifications"}


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
@pytest.mark.parametrize("module", ["email", *CHAT_CHANNELS])
def test_each_outbound_channel_off_skips_its_send_and_on_works_without_the_others(
    module, monkeypatch,
):
    """Channel keys are additive AND gates and have no sibling-channel dependency."""
    makerspace = space(f"offstate-{module}")

    if module == "email":
        skipped = email_dispatch(makerspace)
        assert skipped.status == EmailLog.Status.SKIPPED
        assert mail.outbox == []
        # Return reminders are a duty-of-care exception, not optional tenant mail.
        assert email_dispatch(makerspace, "return_reminder").status == EmailLog.Status.SENT
    else:
        sender = Mock(return_value=True)
        monkeypatch.setattr("apps.integrations.dispatch_channels._channel_configured", lambda *args: True)
        monkeypatch.setattr(
            "apps.integrations.dispatch_channels.limits.reserve_notification_quota",
            lambda *args: True,
        )
        target = ("apps.integrations.telegram.send_message" if module == "telegram"
                  else "apps.integrations.webhooks.send_webhook")
        monkeypatch.setattr(target, sender)
        skipped = channel_dispatch(makerspace, module)
        assert skipped.status == NotificationDeliveryStatus.SKIPPED
        assert skipped.error == "notification_channel_module_disabled"
        sender.assert_not_called()

    enable_only_notification_module(makerspace, module)

    if module == "email":
        delivered = email_dispatch(makerspace)
        assert delivered.status == EmailLog.Status.SENT
        assert len(mail.outbox) == 2
    else:
        delivered = channel_dispatch(makerspace, module)
        assert delivered.status == NotificationDeliveryStatus.SENT
        sender.assert_called_once()
        if module == "telegram":
            # Telegram is outbound-only: a send cannot smuggle an action keyboard in.
            assert "reply_markup" not in sender.call_args.kwargs

    assert set(makerspace.enabled_modules) & MODULE_KEYS == {module}


@override_settings(TELEGRAM_WEBHOOK_SECRET="offstate-secret")
def test_telegram_off_still_acknowledges_and_discards_legacy_callbacks():
    """The retained webhook is a compatibility sink, not a Telegram-owned action API."""
    makerspace = space("offstate-telegram-webhook")
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=active_user("offstate-callback-requester"),
        requester_username="offstate-callback-requester",
        status=HardwareRequest.Status.PENDING_APPROVAL,
    )

    response = APIClient().post(
        reverse("telegram-webhook"),
        {"callback_query": {"from": {"id": 42}, "data": f"accept:{request.pk}"}},
        format="json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="offstate-secret",
    )

    assert response.status_code == 200
    assert response.data["detail"] == "Ignored."
    request.refresh_from_db()
    assert request.status == HardwareRequest.Status.PENDING_APPROVAL


def test_all_notification_modules_off_leave_submit_issue_and_return_working(
    monkeypatch, django_capture_on_commit_callbacks,
):
    """Exercise the core spine plus handover with every alert sink deliberately absent.

    Preferences are forced on so each lifecycle event reaches every outbound dispatch
    gate.  The resulting SKIPPED rows prove suppression happened downstream rather than
    by avoiding notification code entirely.
    """
    makerspace = space("offstate-loan-spine", "guest_handover")
    for channel in (
        NotificationChannel.EMAIL,
        NotificationChannel.TELEGRAM,
        NotificationChannel.SLACK,
        NotificationChannel.DISCORD,
        NotificationChannel.MATTERMOST,
    ):
        NotificationPreference.objects.create(
            makerspace=makerspace,
            feature=NotificationFeature.HARDWARE_REQUESTS,
            channel=channel,
            enabled=True,
        )
    product = InventoryProduct.objects.create(
        makerspace=makerspace,
        name="Torque wrench",
        total_quantity=2,
        available_quantity=2,
        is_public=True,
    )
    requester = active_user("offstate-spine-requester")
    staff = staff_user("offstate-spine")
    staff_client = client_for(staff)
    monkeypatch.setattr(
        "apps.evidence.storage.finalize_upload",
        Mock(return_value=EvidenceValidationResult(size=123, content_type="image/jpeg")),
    )

    with django_capture_on_commit_callbacks(execute=True):
        catalog = APIClient().get(reverse("inventory:public-inventory", args=[makerspace.slug]))
        assert catalog.status_code == 200
        submitted = client_for(requester).post(
            reverse("hardware_requests:request-submit", args=[makerspace.slug]),
            {
                "requested_for": "Off-state contract",
                "items": [{"product_id": product.pk, "quantity": 1}],
            },
            format="json",
        )
        assert submitted.status_code == 201
        queue = staff_client.get(reverse("hardware_requests:pending-requests", args=[makerspace.pk]))
        assert queue.status_code == 200 and queue.data["count"] == 1
        request_id = queue.data["results"][0]["id"]
        accepted = staff_client.post(
            reverse("hardware_requests:request-accept", args=[request_id]), {}, format="json"
        )
        assert accepted.status_code == 200
        public_status = APIClient().get(
            reverse("hardware_requests:request-status", args=[submitted.data["public_token"]])
        )
        assert public_status.status_code == 200
        assert public_status.data["status"] == HardwareRequest.Status.ACCEPTED
        box = Box.objects.create(makerspace=makerspace, label="Off-state box")
        assigned = staff_client.post(
            reverse("hardware_requests:request-assign-box", args=[request_id]),
            {"box_code": box.code},
            format="json",
        )
        assert assigned.status_code == 200
        issued = staff_client.post(
            reverse("hardware_requests:request-issue", args=[request_id]),
            {
                "evidence_id": make_issue_evidence(makerspace, staff).pk,
                "remark": "Issued with all channels off.",
            },
            format="json",
        )
        assert issued.status_code == 200
        request = HardwareRequest.objects.get(pk=request_id)
        returned = staff_client.post(
            reverse("hardware_requests:request-return", args=[request_id]),
            return_payload(request, make_return_evidence(makerspace, staff)),
            format="json",
        )
        assert returned.status_code == 200

    assert returned.data["status"] == HardwareRequest.Status.RETURNED
    assert not Notification.objects.filter(makerspace=makerspace).exists()
    assert set(makerspace.enabled_modules) & MODULE_KEYS == set()
    assert set(NotificationDeliveryLog.objects.filter(makerspace=makerspace).values_list(
        "channel", flat=True
    )) == set(CHAT_CHANNELS)
    assert not NotificationDeliveryLog.objects.filter(
        makerspace=makerspace
    ).exclude(status=NotificationDeliveryStatus.SKIPPED).exists()
    assert EmailLog.objects.filter(makerspace=makerspace).exists()
    assert not EmailLog.objects.filter(makerspace=makerspace).exclude(
        status=EmailLog.Status.SKIPPED
    ).exists()
