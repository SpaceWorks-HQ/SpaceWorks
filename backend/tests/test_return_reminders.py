import logging
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.hardware_requests.services_return_reminders import run_return_reminders
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from tests.tenant_migration.source_gate_helpers import close_gate, make_actor

pytestmark = pytest.mark.django_db


def make_user(username, role=User.Role.REQUESTER, **kw):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@e.com", role=role, **kw
    )


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_product(makerspace):
    return InventoryProduct.objects.create(
        makerspace=makerspace,
        name=f"Product {makerspace.slug}",
        total_quantity=1,
        available_quantity=0,
        issued_quantity=1,
        is_public=True,
    )


def make_request(makerspace, product, *, status, contact_email, due_at):
    requester = make_user(
        f"reminder-{makerspace.slug}-{status}-{contact_email.split('@')[0]}",
        access_status=User.AccessStatus.ACTIVE,
    )
    hardware_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        requester_contact_email=contact_email,
        status=status,
        return_due_at=due_at,
    )
    HardwareRequestItem.objects.create(
        request=hardware_request,
        product=product,
        requested_quantity=1,
        accepted_quantity=1,
        issued_quantity=1,
    )
    return hardware_request


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_send_return_reminders_emails_only_overdue_active_unreminded_requests(mailoutbox):
    now = timezone.now()
    makerspace = make_space("return-reminders")
    product = make_product(makerspace)
    overdue = make_request(
        makerspace,
        product,
        status=HardwareRequest.Status.ISSUED,
        contact_email="overdue@example.com",
        due_at=now - timedelta(minutes=5),
    )
    returned = make_request(
        makerspace,
        product,
        status=HardwareRequest.Status.RETURNED,
        contact_email="returned@example.com",
        due_at=now - timedelta(days=1),
    )
    future = make_request(
        makerspace,
        product,
        status=HardwareRequest.Status.ISSUED,
        contact_email="future@example.com",
        due_at=now + timedelta(days=1),
    )
    archived_space = make_space("archived-return-reminders")
    archived_space.archived_at = now
    archived_space.save(update_fields=["archived_at"])
    archived_product = make_product(archived_space)
    archived = make_request(
        archived_space,
        archived_product,
        status=HardwareRequest.Status.ISSUED,
        contact_email="archived@example.com",
        due_at=now - timedelta(minutes=5),
    )

    out = StringIO()
    call_command("send_return_reminders", stdout=out)

    assert "Return reminders sent: 1" in out.getvalue()
    assert [message.to for message in mailoutbox] == [["overdue@example.com"]]
    assert "return reminder" in mailoutbox[0].subject
    overdue.refresh_from_db()
    returned.refresh_from_db()
    future.refresh_from_db()
    archived.refresh_from_db()
    assert overdue.return_reminder_sent_at is not None
    assert returned.return_reminder_sent_at is None
    assert future.return_reminder_sent_at is None
    assert archived.return_reminder_sent_at is None

    call_command("send_return_reminders", stdout=StringIO())
    assert len(mailoutbox) == 1


def test_send_return_reminders_skips_superadmin_hidden_space(mailoutbox, monkeypatch):
    now = timezone.now()
    hidden_space = make_space("hidden-return-reminders")
    hidden_space.superadmin_access_enabled = False
    hidden_space.save(update_fields=["superadmin_access_enabled"])
    product = make_product(hidden_space)
    overdue = make_request(
        hidden_space,
        product,
        status=HardwareRequest.Status.ISSUED,
        contact_email="hidden-overdue@example.com",
        due_at=now - timedelta(minutes=5),
    )
    calls = []
    monkeypatch.setattr(
        "apps.hardware_requests.services_return_reminders.notifications.notify_return_due",
        lambda request: calls.append(request.pk) or True,
    )

    result = run_return_reminders(now=now)

    assert result == {"sent": 0, "skipped": 0}
    assert calls == []
    assert mailoutbox == []
    overdue.refresh_from_db()
    assert overdue.return_reminder_sent_at is None


def test_frozen_tenant_does_not_stop_return_reminder_fanout(monkeypatch, caplog):
    now = timezone.now()
    first_space = make_space("reminder-fanout-first")
    frozen_space = make_space("reminder-fanout-frozen")
    last_space = make_space("reminder-fanout-last")
    first = make_request(
        first_space,
        make_product(first_space),
        status=HardwareRequest.Status.ISSUED,
        contact_email="first@example.com",
        due_at=now - timedelta(minutes=3),
    )
    frozen = make_request(
        frozen_space,
        make_product(frozen_space),
        status=HardwareRequest.Status.ISSUED,
        contact_email="frozen@example.com",
        due_at=now - timedelta(minutes=2),
    )
    last = make_request(
        last_space,
        make_product(last_space),
        status=HardwareRequest.Status.ISSUED,
        contact_email="last@example.com",
        due_at=now - timedelta(minutes=1),
    )
    close_gate(frozen_space, make_actor("reminder-fanout"))
    delivered = []
    monkeypatch.setattr(
        "apps.hardware_requests.services_return_reminders.notifications.notify_return_due",
        lambda request: delivered.append(request.pk) or True,
    )
    monkeypatch.setattr(
        "apps.hardware_requests.services_return_reminders.emit_notification",
        lambda *args, **kwargs: None,
    )

    with caplog.at_level(
        logging.INFO, logger="apps.tenant_migration.gate_runtime"
    ):
        result = run_return_reminders(now=now)

    assert result == {"sent": 2, "skipped": 1}
    assert delivered == [first.pk, last.pk]
    assert any(
        record.msg == "tenant_fanout_skipped_closed_source_gate"
        and record.makerspace_id == frozen_space.pk
        and record.operation == "return_reminder"
        for record in caplog.records
    )
    first.refresh_from_db()
    frozen.refresh_from_db()
    last.refresh_from_db()
    assert first.return_reminder_sent_at == now
    assert frozen.return_reminder_sent_at is None
    assert last.return_reminder_sent_at == now


def test_run_return_reminders_does_not_send_when_request_already_claimed(monkeypatch):
    now = timezone.now()
    makerspace = make_space("return-reminder-claimed")
    product = make_product(makerspace)
    hardware_request = make_request(
        makerspace,
        product,
        status=HardwareRequest.Status.ISSUED,
        contact_email="claimed@example.com",
        due_at=now - timedelta(minutes=5),
    )
    hardware_request.return_reminder_sent_at = now - timedelta(minutes=1)
    hardware_request.save(update_fields=["return_reminder_sent_at"])
    calls = []

    monkeypatch.setattr(
        "apps.hardware_requests.services_return_reminders.notifications.notify_return_due",
        lambda request: calls.append(request.pk) or True,
    )

    result = run_return_reminders(now=now)

    assert result == {"sent": 0, "skipped": 0}
    assert calls == []

def test_run_return_reminders_resets_claim_when_send_raises(monkeypatch):
    now = timezone.now()
    makerspace = make_space("return-reminder-send-raises")
    product = make_product(makerspace)
    hardware_request = make_request(
        makerspace,
        product,
        status=HardwareRequest.Status.ISSUED,
        contact_email="raises@example.com",
        due_at=now - timedelta(minutes=5),
    )

    def fail_send(_request):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(
        "apps.hardware_requests.services_return_reminders.notifications.notify_return_due",
        fail_send,
    )

    with pytest.raises(RuntimeError):
        run_return_reminders(now=now)

    hardware_request.refresh_from_db()
    assert hardware_request.return_reminder_sent_at is None
