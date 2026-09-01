import json

import pytest

from apps.backup import archive_builder, quiescence
from apps.backup.settings_policy import Policy


def test_manifest_never_contains_raw_continuity_or_infrastructure_secrets(monkeypatch):
    secrets = {
        "SECRET_KEY": "continuity-secret-sentinel",
        "AWS_SECRET_ACCESS_KEY": "infrastructure-secret-sentinel",
        "DATABASE_URL": "postgres://database-secret-sentinel@example/db",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)

    manifest = archive_builder._settings_manifest()
    encoded = json.dumps(manifest)

    assert not any(value in encoded for value in secrets.values())
    assert manifest["SECRET_KEY"]["policy"] == Policy.EXACT_FINGERPRINT
    assert manifest["AWS_SECRET_ACCESS_KEY"] == {
        "policy": Policy.CAPABILITY_PROBE,
        "blocks_restore": True,
        "configured": True,
    }


def test_presigned_write_drain_uses_the_declared_ttl(settings):
    settings.BACKUP_PRESIGN_DRAIN_SECONDS = 731
    observed = []
    archive_builder.drain_presigned_uploads(sleep=observed.append)
    assert observed == [731]


def test_unversioned_backup_pauses_and_checks_background_writers(monkeypatch, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    events = []

    class Control:
        def cancel_consumer(self, queue, **_kwargs):
            events.append(("pause", queue))
            return [{"worker": {"ok": "cancelled"}}]

        def inspect(self, **_kwargs):
            return type("Inspect", (), {"active": lambda self: {"worker": []}})()

        def add_consumer(self, queue, **_kwargs):
            events.append(("resume", queue))
            return [{"worker": {"ok": "started"}}]

    monkeypatch.setattr(quiescence.current_app, "control", Control())
    monkeypatch.setattr(quiescence.current_app.conf, "task_default_queue", "celery")

    paused = quiescence.pause_worker_consumers()
    quiescence.assert_workers_drained()
    quiescence.resume_worker_consumers(paused)

    assert events == [("pause", "celery"), ("resume", "celery")]


def test_unversioned_backup_refuses_to_claim_consistency_with_active_writers(
    monkeypatch, settings
):
    settings.CELERY_TASK_ALWAYS_EAGER = False

    class Inspect:
        def active(self):
            return {"worker": [{"name": "apps.notifications.tasks.deliver"}]}

    monkeypatch.setattr(
        quiescence.current_app.control,
        "inspect",
        lambda **_kwargs: Inspect(),
    )
    with pytest.raises(quiescence.QuiescenceError, match="did not drain"):
        quiescence.assert_workers_drained()
