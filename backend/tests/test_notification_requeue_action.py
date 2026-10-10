"""The `/control/` dead-letter action for chat/webhook deliveries (cloud-completeness lane).

`NotificationDeliveryLogAdmin.requeue_failed_deliveries` is the only way a superadmin gets a
delivery that exhausted its Celery retries moving again. It shipped without a test. Pinned:
only FAILED rows move, each re-queue is audited, the row is handed to the same enqueue path
the dispatcher uses, a broker outage leaves the row FAILED rather than stuck PENDING, and
the action is unreachable for anyone but a superadmin.
"""

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.integrations import dispatch_channels
from apps.integrations.models import NotificationDeliveryLog
from apps.integrations.notification_enums import (
    NotificationDeliveryStatus,
    NotificationFeature,
)
from tests.return_helpers import make_member, make_space, make_user
from tests.accounts.mfa_helpers import force_mfa_login

pytestmark = pytest.mark.django_db

URL_NAME = "admin:integrations_notificationdeliverylog_changelist"


def _superadmin(username):
    return make_user(
        username, role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE,
        is_staff=True, is_superuser=True,
    )


def _log(space, status, error=""):
    return NotificationDeliveryLog.objects.create(
        makerspace=space, channel="slack", feature=NotificationFeature.HARDWARE_REQUESTS,
        event="request.accepted", text_body="Request #3 accepted", status=status,
        error=error, attempts=4,
    )


def _post(client, rows):
    return client.post(
        reverse(URL_NAME),
        {
            "action": "requeue_failed_deliveries",
            ACTION_CHECKBOX_NAME: [str(row.pk) for row in rows],
            "index": "0",
        },
        follow=True,
    )


def test_requeue_moves_only_failed_rows_audits_and_enqueues(monkeypatch):
    space = make_space("requeue-action")
    failed = _log(space, NotificationDeliveryStatus.FAILED, "notification_delivery_failed:Timeout")
    sent = _log(space, NotificationDeliveryStatus.SENT)
    skipped = _log(space, NotificationDeliveryStatus.SKIPPED, "notification_channel_module_disabled")
    enqueued = []
    monkeypatch.setattr(dispatch_channels, "_enqueue_notification", enqueued.append)
    client = Client()
    force_mfa_login(client, _superadmin("requeue-super"))

    response = _post(client, [failed, sent, skipped])

    assert response.status_code == 200
    assert enqueued == [failed.pk]
    failed.refresh_from_db()
    sent.refresh_from_db()
    skipped.refresh_from_db()
    assert (failed.status, failed.error) == (NotificationDeliveryStatus.PENDING, "")
    assert sent.status == NotificationDeliveryStatus.SENT
    assert skipped.status == NotificationDeliveryStatus.SKIPPED
    audits = AuditLog.objects.filter(action="notification.delivery_requeued")
    assert [a.target_id for a in audits] == [str(failed.pk)]
    assert audits.get().meta == {"channel": "slack", "event": "request.accepted", "attempts": 4}


def test_requeue_with_the_broker_down_leaves_the_row_failed(monkeypatch):
    from apps.integrations import tasks

    space = make_space("requeue-broker-down")
    failed = _log(space, NotificationDeliveryStatus.FAILED, "notification_delivery_failed:Timeout")

    def broker_down(log_id):
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr(tasks.deliver_notification_task, "delay", broker_down)
    client = Client()
    force_mfa_login(client, _superadmin("requeue-broker-super"))

    response = _post(client, [failed])

    assert response.status_code == 200
    failed.refresh_from_db()
    assert failed.status == NotificationDeliveryStatus.FAILED
    assert failed.error == "notification_delivery_failed:ConnectionError"


def test_a_space_manager_cannot_reach_the_requeue_action(monkeypatch):
    space = make_space("requeue-denied")
    failed = _log(space, NotificationDeliveryStatus.FAILED, "notification_delivery_failed:Timeout")
    manager = make_member("requeue-manager", space)
    manager.is_staff = True
    manager.save(update_fields=["is_staff"])
    monkeypatch.setattr(
        dispatch_channels, "_enqueue_notification",
        lambda *_: pytest.fail("a non-superadmin must not re-queue"),
    )
    client = Client()
    force_mfa_login(client, manager)

    response = _post(client, [failed])

    assert response.status_code in {302, 403, 404} or response.redirect_chain
    failed.refresh_from_db()
    assert failed.status == NotificationDeliveryStatus.FAILED
    assert not AuditLog.objects.filter(action="notification.delivery_requeued").exists()
