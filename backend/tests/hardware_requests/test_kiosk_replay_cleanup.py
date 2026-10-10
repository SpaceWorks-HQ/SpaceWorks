from datetime import timedelta

import pytest
from django.utils import timezone

from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import ReplayCommand
from apps.hardware_requests.replay_cleanup import cleanup_replay_commands
from tests.hardware_requests.replay_helpers import envelope, execute, prepare, replay_env

pytestmark = pytest.mark.django_db


def test_expiry_is_bounded_and_never_deletes_evidence(replay_env, settings):
    env = replay_env
    settings.KIOSK_REPLAY_CLEANUP_BATCH_SIZE = 1
    for _ in range(2):
        assert prepare(env, envelope(env, "reviewed_issue", {"request_id": env.request.pk})).status_code == 200
    ReplayCommand.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert cleanup_replay_commands()["expired"] == 1
    assert ReplayCommand.objects.filter(state="prepared").count() == 1
    assert EvidencePhoto.objects.count() == 2
    now = timezone.now() + timedelta(days=8)
    counts = cleanup_replay_commands(now=now)
    assert counts["deleted"] == 1 and EvidencePhoto.objects.count() == 2


def test_retained_descendant_protects_predecessor_and_old_envelope_cannot_reopen(replay_env):
    env = replay_env
    first = envelope(env)
    assert prepare(env, first).status_code == execute(env, first).status_code == 200
    second = envelope(env, aggregate_id=first["aggregate_id"], sequence=2,
                      predecessor_client_id=first["client_command_id"])
    assert prepare(env, second).status_code == execute(env, second).status_code == 200
    old = timezone.now() - timedelta(days=8)
    ReplayCommand.objects.filter(client_command_id=first["client_command_id"]).update(completed_at=old, expires_at=old)
    assert cleanup_replay_commands()["deleted"] == 0
    ReplayCommand.objects.filter(client_command_id=second["client_command_id"]).update(completed_at=old, expires_at=old)
    assert cleanup_replay_commands()["deleted"] == 1
    assert cleanup_replay_commands()["deleted"] == 1
    first["client_created_at"] = old.isoformat()
    assert prepare(env, first).data["code"] == "command_expired"
    assert not ReplayCommand.objects.exists()


def test_closed_source_gate_skips_cleanup(replay_env):
    from tests.tenant_migration.source_gate_helpers import close_gate, make_actor
    env = replay_env
    data = envelope(env)
    assert prepare(env, data).status_code == 200
    ReplayCommand.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    close_gate(env.space, make_actor())
    counts = cleanup_replay_commands()
    assert counts["skipped"] == 1 and counts["expired"] == 0
    assert ReplayCommand.objects.get().state == "prepared"


def test_cleanup_does_not_touch_a_fresh_claim(replay_env):
    from uuid import uuid4
    env = replay_env
    assert prepare(env, envelope(env)).status_code == 200
    ReplayCommand.objects.update(state="claimed", claim_token=uuid4(), claimed_at=timezone.now(),
                                 expires_at=timezone.now() - timedelta(seconds=1))
    assert cleanup_replay_commands()["expired"] == 0
    assert ReplayCommand.objects.get().state == "claimed"
