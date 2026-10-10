"""SMTP timeouts and a broker outage retain sanitized, retryable evidence."""

import logging
import socket
from smtplib import SMTPServerDisconnected

import pytest
from django.core.mail import EmailMultiAlternatives

from apps.integrations import dispatch
from apps.integrations.models import EmailLog
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("error", [socket.timeout("smtp-password-secret"), SMTPServerDisconnected("smtp-password-secret")])
def test_smtp_failure_notifies_staff_once_and_never_exposes_secret(monkeypatch, caplog, error):
    space = make_space("smtp-failure")
    notices = []
    monkeypatch.setattr("apps.notifications.emit.emit_notification", lambda *a, **k: notices.append(k))

    def send(self):
        raise error

    monkeypatch.setattr(EmailMultiAlternatives, "send", send)
    with caplog.at_level(logging.DEBUG):
        log = dispatch.dispatch_email(
            to_email="member@example.com", subject="Reminder", text_body="Return due",
            makerspace=space, sync=True,
        )
        dispatch._deliver(log)
    log.refresh_from_db()
    assert log.status == EmailLog.Status.FAILED
    assert log.attempts == 2 and log.sent_at is None
    assert len(notices) == 1 and notices[0]["event"] == "email.failed"
    assert "smtp-password-secret" not in log.error
    assert "smtp-password-secret" not in caplog.text


def test_broker_failure_records_failed_row_without_echoing_the_connection_url(monkeypatch, caplog):
    from apps.integrations.tasks import deliver_email_task

    log = EmailLog.objects.create(to_email="member@example.com", subject="Queued", text_body="body")

    def delay(*args):
        raise ConnectionError("redis://user:private-broker-password@broker:6379")

    monkeypatch.setattr(deliver_email_task, "delay", delay)
    with caplog.at_level(logging.DEBUG):
        dispatch._enqueue(log.pk)
    log.refresh_from_db()
    assert log.status == EmailLog.Status.FAILED
    assert log.error == "email_delivery_failed:ConnectionError"
    assert "private-broker-password" not in caplog.text
