from django.db import models

from apps.data_export.classification import OMITTED_MODELS
from apps.operations.models import ReminderSchedule
from apps.tenant_migration.gate_policy_tasks import (
    FANOUT_GATE_PARTICIPANTS, TASK_INTERNAL_PARTICIPANTS,
)
from apps.tenant_migration.target_projection import ROW_POLICIES, RowDisposition
from apps.tenant_migration.tenant_dump_catalog import FIELD_POLICIES
from apps.tenant_migration.tenant_dump_field_snapshot import FIRST_PARTY_FIELD_NAMES
from apps.tenant_migration.tenant_dump_model_catalog import FIRST_PARTY_MODEL_RULES
from apps.tenant_migration.tenant_dump_types import AuthorityDisposition, ModelDisposition


def test_reminder_coordination_does_not_travel_or_pull_users_into_export():
    label = ReminderSchedule._meta.label
    assert label in OMITTED_MODELS
    assert FIRST_PARTY_MODEL_RULES[label].disposition == ModelDisposition.DROP
    assert ROW_POLICIES[label].disposition == RowDisposition.DROP
    assert FIRST_PARTY_FIELD_NAMES[label] == frozenset(
        field.name for field in ReminderSchedule._meta.fields
    )
    for field in ReminderSchedule._meta.fields:
        assert FIELD_POLICIES[(label, field.name)].dispositions == (AuthorityDisposition.DROP,)
        if isinstance(field, models.ForeignKey):
            assert field.related_model._meta.label != "accounts.User"


def test_shared_sweeper_declares_both_source_gate_participants():
    assert "apps.operations.tasks_reminders.run_reminder_sweep_task" in TASK_INTERNAL_PARTICIPANTS
    assert "apps.operations.reminder_sweeper.run_reminder_sweep" in FANOUT_GATE_PARTICIPANTS
