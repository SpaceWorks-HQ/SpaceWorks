import pytest

from apps.integrations.destinations import NotificationScope
from apps.integrations.notifications_machine_scope import reminder_staff_ids
from apps.integrations.staff_notifications import staff_emails_for_feature, staff_user_ids_for_feature
from apps.machines.models import Machine, MakerspaceMachineTypePolicy
from apps.data_export.classification import EXPORTED_MODEL_FIELDS
from apps.data_export.datasets import DATASET_SPECS
from apps.tenant_migration.tenant_dump_field_snapshot import FIRST_PARTY_FIELD_NAMES
from apps.tenant_migration.tenant_dump_model_catalog import FIRST_PARTY_MODEL_RULES
from apps.tenant_migration.target_projection_references import FK_POLICIES
from apps.tenant_migration.authority_guards import DECLARED_AUTHORITY_FIELDS
from apps.tenant_migration.tenant_dump_authority import AUTHORITY_FIELD_OVERRIDES
from apps.tenant_migration.tenant_dump_types import AuthorityDisposition
from tests.machines.certification_helpers import _space, _machine_type, _manager

pytestmark = pytest.mark.django_db


def test_machine_reminders_refuse_unlinked_and_other_type_roles():
    space = _space("rem-scope", modules=("machines", "maintenance", "notifications"))
    laser, printer = _machine_type(space, "Laser"), _machine_type(space, "Printer")
    manager, _ = _manager(space, "rem-scope-laser", laser)
    other, _ = _manager(space, "rem-scope-printer", printer)
    unlinked, _ = _manager(space, "rem-scope-none")
    machine = Machine.objects.create(makerspace=space, machine_type=laser, name="Laser")
    assert reminder_staff_ids(space, "maintenance", "overdue", NotificationScope(machine=machine)) == {manager.pk}
    assert reminder_staff_ids(space, "certifications", "expiring", NotificationScope(machine_type=laser.pk)) == {manager.pk}
    assert manager.email in staff_emails_for_feature(space, "maintenance", "overdue", NotificationScope(machine=machine))
    assert other.email not in staff_emails_for_feature(space, "maintenance", "overdue", NotificationScope(machine=machine))
    assert unlinked.email not in staff_emails_for_feature(space, "maintenance", "overdue", NotificationScope(machine=machine))
    assert staff_user_ids_for_feature(space, "maintenance", "overdue", NotificationScope(machine=machine)) == [manager.pk]
    # The existing interactive fallback deliberately treats an unlinked role as
    # unconfigured. Strict timer filtering must not silently change that contract.
    assert unlinked.email in staff_emails_for_feature(space, "maintenance", "schedule_created", NotificationScope(machine=machine))


def test_timer_recipient_queries_refuse_a_hidden_tenant():
    space = _space("rem-hidden", modules=("machines", "maintenance", "notifications"))
    kind = _machine_type(space)
    manager, _ = _manager(space, "rem-hidden-manager", kind)
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Laser")
    scope = NotificationScope(machine=machine)
    assert staff_emails_for_feature(space, "maintenance", "overdue", scope) == [manager.email]
    space.superadmin_access_enabled = False
    space.save(update_fields=["superadmin_access_enabled"])
    assert staff_emails_for_feature(space, "maintenance", "overdue", scope) == []
    assert staff_user_ids_for_feature(space, "maintenance", "overdue", scope) == []


def test_policy_has_explicit_export_snapshot_and_type_remapping_without_user_edges():
    label = MakerspaceMachineTypePolicy._meta.label
    names = {field.name for field in MakerspaceMachineTypePolicy._meta.fields}
    assert names == set(EXPORTED_MODEL_FIELDS[label].split())
    assert names == FIRST_PARTY_FIELD_NAMES[label]
    assert label in FIRST_PARTY_MODEL_RULES and label in DATASET_SPECS
    assert (label, "machine_type") in FK_POLICIES
    assert all(not field.is_relation or field.related_model._meta.label != "accounts.User"
               for field in MakerspaceMachineTypePolicy._meta.fields)
    assert {(label, field) for field in names - {"id"}} <= set(DECLARED_AUTHORITY_FIELDS)
    assert ("maintenance.MaintenanceSchedule", "anchor") in DECLARED_AUTHORITY_FIELDS
    assert all(AUTHORITY_FIELD_OVERRIDES[(label, field)].dispositions == (AuthorityDisposition.PRESERVE,)
               for field in names)


def test_portable_projection_retains_numeric_policy_but_resets_reminder_opt_in():
    from apps.backup.raw_projection import raw_records
    from apps.tenant_migration.tenant_dump_raw import sanitize_record
    from apps.makerspaces.models import Makerspace
    space = _space("rem-policy-projection", modules=("machines", "notifications"))
    space.enabled_features = ["machines.certification_reminders"]
    space.save(update_fields=["enabled_features"])
    kind = _machine_type(space)
    policy = MakerspaceMachineTypePolicy.objects.create(
        makerspace=space, machine_type=kind, cert_reminder_days=5, reminder_lead_days=0, grace_days=2,
    )
    source = raw_records(MakerspaceMachineTypePolicy.objects.filter(pk=policy.pk), MakerspaceMachineTypePolicy)[0]
    projected = sanitize_record(MakerspaceMachineTypePolicy, source).values
    assert projected["cert_reminder_days"] == 5 and projected["reminder_lead_days"] == 0 and projected["grace_days"] == 2
    source_space = raw_records(Makerspace.objects.filter(pk=space.pk), Makerspace)[0]
    assert "machines.certification_reminders" not in sanitize_record(Makerspace, source_space).values["enabled_features"]
