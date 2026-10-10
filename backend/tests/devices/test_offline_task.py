"""Task catalogs, per-tenant source gates and canonical runtime filtering."""

from datetime import timedelta
import importlib

import pytest
from django.utils import timezone

from apps.devices.models import Device, DeviceEvent
from apps.devices.services_offline import scan_offline_devices
from apps.devices.tasks import scan_offline_devices_task
from apps.makerspaces.models import Makerspace
from tests.devices.helpers import active_device
from tests.module_helpers import disable_module
from tests.tenant_migration.source_gate_helpers import close_gate, make_actor

pytestmark = pytest.mark.django_db


def _stale(slug):
    space, _manager, _client, device_id, _key = active_device(slug)
    Device.objects.filter(pk=device_id).update(last_seen_at=timezone.now()-timedelta(hours=1))
    return space, device_id


def test_frozen_tenant_is_skipped_and_other_tenant_is_processed():
    blocked, blocked_id = _stale("offline-frozen")
    live, live_id = _stale("offline-live")
    close_gate(blocked, make_actor("offline-gate"))
    result = scan_offline_devices_task()
    assert (result["scanned"], result["skipped"], result["offline"]) == (1, 1, 1)
    assert Device.objects.get(pk=blocked_id).offline_since is None
    assert Device.objects.get(pk=live_id).offline_since is not None
    assert DeviceEvent.objects.filter(makerspace=live, event_type="offline_detected").exists()


@pytest.mark.parametrize("state", ["archived", "importing", "aborted", "module_off"])
def test_unservable_and_module_off_tenants_are_excluded(state):
    space, device_id = _stale(f"offline-{state}")
    if state == "archived":
        Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now())
    elif state == "module_off":
        disable_module(space, "devices")
    else:
        Makerspace.objects.filter(pk=space.pk).update(lifecycle_state=state)
    assert scan_offline_devices()["scanned"] == 0
    assert Device.objects.get(pk=device_id).offline_since is None


def test_tombstoned_runtime_does_no_work(monkeypatch):
    _space, device_id = _stale("offline-tombstone")
    monkeypatch.setattr("apps.devices.services_offline.module_available", lambda _key: False)
    assert scan_offline_devices()["scanned"] == 0
    assert Device.objects.get(pk=device_id).offline_since is None


def test_task_and_service_are_declared_and_gate_policy_barrel_is_exact():
    from apps.tenant_migration import gate_policy, gate_policy_http, gate_policy_tasks, gate_policy_objects
    from apps.tenant_migration.source_gate_guards import validate_task_coverage
    from apps.tenant_migration.source_gate_fanout_guards import validate_fanout_gate_coverage
    assert "apps.devices.tasks.scan_offline_devices_task" in gate_policy.TASK_INTERNAL_PARTICIPANTS
    assert "apps.devices.services_offline.scan_offline_devices" in gate_policy.FANOUT_GATE_PARTICIPANTS
    for module in (gate_policy_http, gate_policy_tasks, gate_policy_objects):
        for name, value in vars(module).items():
            if name.isupper():
                assert getattr(gate_policy, name) is value
    validate_task_coverage()
    validate_fanout_gate_coverage()


def test_beatless_tombstone_filter_removes_device_task(settings):
    from apps.operations.management.commands import run_scheduled_tasks as module
    original = settings.TOMBSTONED_APPS
    try:
        settings.TOMBSTONED_APPS = set(original) | {"devices"}
        importlib.reload(module)
        assert not any(".devices." in path for _, path, _ in module.SCHEDULED_TASKS)
    finally:
        settings.TOMBSTONED_APPS = original
        importlib.reload(module)


def test_beat_settings_remove_exact_same_device_task_when_tombstoned():
    import ast
    from pathlib import Path
    settings_file = Path(__file__).resolve().parents[2] / "config" / "settings.py"
    tree = ast.parse(settings_file.read_text(encoding="utf-8-sig"))
    block = next(node for node in tree.body if isinstance(node, ast.If)
                 and ast.unparse(node.test) == "'devices' in TOMBSTONED_APPS")
    state = {"TOMBSTONED_APPS": {"devices"}, "CELERY_BEAT_SCHEDULE": {
        "scan-offline-devices": {"task": "apps.devices.tasks.scan_offline_devices_task"},
        "keep": {"task": "apps.accounts.tasks.purge_auth_challenges_task"},
    }}
    exec(compile(ast.Module(body=[block], type_ignores=[]), str(settings_file), "exec"), state)
    assert set(state["CELERY_BEAT_SCHEDULE"]) == {"keep"}
