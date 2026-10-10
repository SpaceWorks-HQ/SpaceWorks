from datetime import timedelta

import pytest
from django.utils import timezone

from apps.boxes.models import BoxScan
from apps.evidence.models import EvidenceUploadFinalization
from apps.hardware_requests.models import ReplayCommand
from apps.hardware_requests.replay_claims import release
from apps.hardware_requests.replay_execute import execute as execute_service
from tests.hardware_requests.replay_helpers import envelope, execute, identity, prepare, replay_env, validated

pytestmark = pytest.mark.django_db(transaction=True)


class ProcessStopped(BaseException):
    """Bypasses ordinary exception cleanup, like a process dying mid-request."""


@pytest.mark.parametrize("boundary", ["before_s3", "after_s3", "inside_domain"])
def test_stale_claim_recovers_each_crash_without_double_issue(replay_env, monkeypatch, boundary):
    env = replay_env
    assigned = envelope(env)
    assert prepare(env, assigned).status_code == execute(env, assigned).status_code == 200
    raw = envelope(env, "reviewed_issue", {"request_id": env.request.pk})
    assert prepare(env, raw).status_code == 200
    data = validated(raw)
    import apps.hardware_requests.replay_execute as runner
    finalize, dispatch = runner.storage.finalize_upload, runner.dispatch
    def stop_finalization(photo, limit):
        if boundary == "after_s3":
            finalize(photo, limit)
        raise ProcessStopped()
    def stop_domain(*args):
        dispatch(*args)
        raise ProcessStopped()
    with monkeypatch.context() as patch:
        if boundary == "inside_domain":
            patch.setattr(runner, "dispatch", stop_domain)
        else:
            patch.setattr(runner.storage, "finalize_upload", stop_finalization)
        with pytest.raises(ProcessStopped):
            execute_service(identity(env), data)
    command = ReplayCommand.objects.get(client_command_id=data["client_command_id"])
    assert command.state == "claimed"
    env.request.refresh_from_db()
    assert env.request.status == "accepted"
    if boundary != "before_s3":
        assert EvidenceUploadFinalization.objects.get(evidence=command.evidence).status == "finalized"
    old_token = command.claim_token
    ReplayCommand.objects.filter(pk=command.pk).update(claimed_at=timezone.now() - timedelta(minutes=6))
    response = execute(env, raw)
    assert response.status_code == 200, response.data
    command.refresh_from_db()
    assert command.state == "succeeded" and command.claim_attempts == 2
    assert release(command.pk, old_token) == 0
    assert execute(env, raw).status_code == 200
    env.request.refresh_from_db()
    assert env.request.status == "issued"
    assert BoxScan.objects.filter(request=env.request).count() == 1


def test_unknown_exception_rolls_back_domain_and_preserves_retryability(replay_env, monkeypatch):
    env = replay_env
    data = envelope(env)
    assert prepare(env, data).status_code == 200
    import apps.hardware_requests.replay_execute as runner
    original = runner.dispatch
    def fault(*args):
        original(*args)
        raise RuntimeError("sensitive exception text must never be returned")
    with monkeypatch.context() as patch:
        patch.setattr(runner, "dispatch", fault)
        response = execute(env, data)
    assert response.status_code == 503 and response.data["code"] == "server_unavailable"
    assert "sensitive" not in str(response.data)
    assert ReplayCommand.objects.get().state == "prepared"
    assert not BoxScan.objects.exists()
    assert execute(env, data).status_code == 200


def test_an_old_executor_cannot_release_a_reclaimed_token(replay_env):
    from django.db import transaction
    from apps.hardware_requests.replay_claims import claim_locked
    env = replay_env
    assert prepare(env, envelope(env)).status_code == 200
    with transaction.atomic():
        command = ReplayCommand.objects.select_for_update().get()
        first = claim_locked(command)
    ReplayCommand.objects.filter(pk=command.pk).update(claimed_at=timezone.now() - timedelta(minutes=6))
    with transaction.atomic():
        command = ReplayCommand.objects.select_for_update().get()
        second = claim_locked(command)
    assert first != second and release(command.pk, first) == 0
    command.refresh_from_db()
    assert command.state == "claimed" and command.claim_token == second
