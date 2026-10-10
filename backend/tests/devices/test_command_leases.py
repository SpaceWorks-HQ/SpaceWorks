from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import close_old_connections
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.devices.errors_printers import LeaseExpired, PrinterConflict
from apps.devices.models import Device, DeviceCommand, PrinterJob
from apps.devices.services_commands import acknowledge, lease_command
from tests.devices.printer_helpers import printer_case
from tests.module_helpers import disable_module

pytestmark = pytest.mark.django_db(transaction=True)


def test_lease_returns_token_once_stores_digest_and_acks_after_long_print():
    case = printer_case("printer-lease")
    now = timezone.now()
    lease = lease_command(case["principal"], now=now)
    command = DeviceCommand.objects.get(pk=lease["command_id"])
    assert command.lease_token_digest != lease["lease_token"] and len(command.lease_token_digest) == 64
    assert command.attempts == 1
    assert lease_command(case["principal"], now=now) is None
    ack = acknowledge(case["principal"], command.pk, lease["lease_token"], now=now)
    assert acknowledge(case["principal"], command.pk, lease["lease_token"], now=now + timedelta(hours=2)).pk == ack.pk
    with pytest.raises(PrinterConflict):
        acknowledge(case["principal"], command.pk, "x" * 43)


def test_expired_ack_commits_requeue_backoff_and_old_token_cannot_ack_new_lease():
    case = printer_case("printer-expiry")
    now = timezone.now()
    lease = lease_command(case["principal"], now=now)
    expired = now + timedelta(seconds=61)
    with pytest.raises(LeaseExpired):
        acknowledge(case["principal"], case["job"].command_id, lease["lease_token"], now=expired)
    command = DeviceCommand.objects.get(pk=case["job"].command_id)
    assert command.status == "queued" and command.lease_token_digest is None
    assert lease_command(case["principal"], now=expired) is None
    second = lease_command(case["principal"], now=command.next_attempt_at)
    assert second and second["lease_token"] != lease["lease_token"]
    with pytest.raises(PrinterConflict):
        acknowledge(case["principal"], command.pk, lease["lease_token"], now=command.next_attempt_at)


@override_settings(DEVICE_COMMAND_MAX_ATTEMPTS=1)
def test_final_expired_attempt_marks_delivery_failed():
    case = printer_case("printer-max-attempt")
    now = timezone.now()
    lease_command(case["principal"], now=now)
    assert lease_command(case["principal"], now=now + timedelta(seconds=61)) is None
    command = DeviceCommand.objects.get(pk=case["job"].command_id)
    assert command.status == "delivery_failed" and command.attempts == 1
    assert PrinterJob.objects.get(pk=case["job"].pk).state == "cancelled"


def test_cross_device_and_revoked_principals_cannot_claim_or_ack():
    case = printer_case("printer-owner")
    other = printer_case("printer-other-owner")
    lease = lease_command(case["principal"])
    with pytest.raises(NotFound):
        acknowledge(other["principal"], case["job"].command_id, lease["lease_token"])
    Device.objects.filter(pk=case["device"].pk).update(status="revoked")
    with pytest.raises(PermissionDenied):
        lease_command(case["principal"])


def test_adapter_off_or_missing_target_cancels_delivery_permanently():
    case = printer_case("printer-disabled")
    disable_module(case["space"], "machine_service")
    assert lease_command(case["principal"]) is None
    command = DeviceCommand.objects.get(pk=case["job"].command_id)
    assert command.status == "cancelled" and command.attempts == 0


def test_rotation_does_not_transfer_command_to_new_key():
    case = printer_case("printer-key-version")
    Device.objects.filter(pk=case["device"].pk).update(key_version=2)
    case["device"].refresh_from_db()
    from apps.devices.principal import DevicePrincipal
    principal = DevicePrincipal.from_device(case["device"])
    assert lease_command(principal) is None
    assert DeviceCommand.objects.get(pk=case["job"].command_id).status == "cancelled"


def test_two_pollers_lease_one_command_exactly_once():
    case = printer_case("printer-concurrent-lease")
    def poll(_):
        close_old_connections()
        try:
            return lease_command(case["principal"])
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(poll, range(2)))
    assert sum(result is not None for result in results) == 1
    assert DeviceCommand.objects.get(pk=case["job"].command_id).attempts == 1
