"""Plural devices activity stays distinct from native mobile-device activity."""

import pytest
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.operations.report_coverage import REPORT_MODULE_COVERAGE
from apps.operations.reports_module_health import build_module_operational_health
from tests.devices.helpers import device_space

pytestmark = pytest.mark.django_db


def test_health_row_counts_offline_as_failure_and_recovery_as_activity():
    space = device_space("device-health", modules=("devices", "mobile"))
    for action in ("devices.offline_detected", "devices.recovered", "devices.command_failed", "device.login"):
        audit.record(None, action, makerspace=space)
    rows = {row["module_key"]: row for row in build_module_operational_health(space.pk).records}
    assert REPORT_MODULE_COVERAGE["devices"].kind == "health_row"
    assert rows["devices"]["activity_count"] == 3
    assert rows["devices"]["failure_count"] == 2
    latest = AuditLog.objects.filter(makerspace=space, action__startswith="devices.").latest("created_at")
    assert rows["devices"]["last_activity_at"] == latest.created_at
    assert rows["mobile"]["activity_count"] == 1
    assert rows["mobile"]["failure_count"] == 0


def test_recovery_is_not_a_failure_and_other_tenant_is_excluded():
    first, second = device_space("device-health-a"), device_space("device-health-b")
    audit.record(None, "devices.recovered", makerspace=first)
    audit.record(None, "devices.offline_detected", makerspace=second)
    row = next(row for row in build_module_operational_health(first.pk).records if row["module_key"] == "devices")
    assert row["activity_count"] == 1 and row["failure_count"] == 0


def test_state_edges_have_portable_typed_device_references():
    from apps.tenant_migration.audit_references_meta import AUDIT_META_REFERENCES
    for action in ("devices.offline_detected", "devices.recovered"):
        assert AUDIT_META_REFERENCES[(action, "device_id")].target_model_label == "devices.Device"
