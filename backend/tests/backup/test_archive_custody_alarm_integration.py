import pytest
from django.contrib import admin
from django.db import transaction

from apps.backup import custody_alarms
from apps.backup.custody import with_makerspace_custody_lock
from apps.backup.models import MakerspaceArchiveCustodyState as CustodyState
from apps.backup.models import ArchiveCustodyAlarmDelivery
from apps.data_export.models import MODELS
from apps.makerspaces.models import Makerspace
from config.admin_access import GLOBAL_ADMIN_MODELS
from tests.backup.archive_custody_alarm_test_helpers import space as alarm_space


pytestmark = pytest.mark.django_db


def test_one_makerspace_intent_error_does_not_stop_sweep(monkeypatch):
    spaces = [
        alarm_space(f"sweep-{i}", CustodyState.State.DEGRADED_ONE_RECIPIENT)
        for i in range(2)
    ]
    seen = []

    def resolve(state_id):
        seen.append(state_id)
        if state_id == spaces[0].archive_custody_state.pk:
            raise RuntimeError("first tenant failed")

    monkeypatch.setattr(custody_alarms, "_ensure_delivery_intents", resolve)
    custody_alarms.deliver_archive_custody_alarms()
    assert seen == [space.archive_custody_state.pk for space in spaces]


def test_transition_enqueue_is_post_commit_and_fail_safe(
    monkeypatch, django_capture_on_commit_callbacks
):
    calls = []

    def fail(makerspace_id):
        calls.append(makerspace_id)
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(
        "apps.backup.tasks.deliver_archive_custody_alarms_task.delay", fail
    )
    makerspace = Makerspace.objects.create(
        name="Enqueue", slug="alarm-enqueue", superadmin_access_enabled=False
    )
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic(), with_makerspace_custody_lock(makerspace.pk):
            pass
        assert calls == []

    assert calls == [makerspace.pk]
    assert CustodyState.objects.filter(makerspace=makerspace).exists()


def test_schedule_and_model_registries_include_custody_alarm():
    from django.conf import settings
    from apps.operations.management.commands.run_scheduled_tasks import SCHEDULED_TASKS

    assert "deliver-archive-custody-alarms" in settings.CELERY_BEAT_SCHEDULE
    assert "deliver-archive-custody-alarms" in {row[0] for row in SCHEDULED_TASKS}
    assert "backup.ArchiveCustodyAlarmDelivery" in MODELS
    assert "backup.archivecustodyalarmdelivery" in GLOBAL_ADMIN_MODELS
    assert ArchiveCustodyAlarmDelivery in admin.site._registry
