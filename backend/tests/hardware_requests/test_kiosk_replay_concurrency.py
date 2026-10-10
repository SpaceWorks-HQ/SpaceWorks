"""These tests require real PostgreSQL connections; coordinator runs them."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from django.db import connections

from apps.boxes.models import BoxScan
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import ReplayCommand
from apps.hardware_requests.replay_execute import execute as execute_service
from apps.hardware_requests.replay_failures import ReplayFailure
from apps.hardware_requests.replay_prepare import prepare as prepare_service
from tests.hardware_requests.replay_helpers import envelope, execute, identity, prepare, replay_env, validated

pytestmark = pytest.mark.django_db(transaction=True)


def in_connection(fn, *args):
    connections.close_all()
    try:
        return fn(*args)
    finally:
        connections.close_all()


def test_concurrent_prepare_creates_one_owner_and_one_evidence(replay_env):
    env = replay_env
    data = validated(envelope(env, "reviewed_issue", {"request_id": env.request.pk}))
    who = identity(env)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(in_connection, prepare_service, who, data) for _ in range(2)]
        rows = [future.result(timeout=20) for future in futures]
    assert rows[0]["replay_id"] == rows[1]["replay_id"]
    assert rows[0]["evidence_id"] == rows[1]["evidence_id"]
    assert ReplayCommand.objects.count() == EvidencePhoto.objects.count() == 1


def test_fresh_claim_collision_executes_one_issue(replay_env, monkeypatch):
    env = replay_env
    assigned = envelope(env)
    assert prepare(env, assigned).status_code == execute(env, assigned).status_code == 200
    data = validated(envelope(env, "reviewed_issue", {"request_id": env.request.pk}))
    prepare_service(identity(env), data)
    started, finish = Event(), Event()
    from apps.evidence.storage import finalize_upload
    def pause(photo, limit):
        started.set()
        assert finish.wait(10), "test did not release finalization"
        return finalize_upload(photo, limit)
    monkeypatch.setattr("apps.hardware_requests.replay_execute.storage.finalize_upload", pause)
    who = identity(env)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(in_connection, execute_service, who, data)
        assert started.wait(10)
        try:
            second = pool.submit(in_connection, execute_service, who, data)
            with pytest.raises(ReplayFailure, match="Another caller"):
                second.result(timeout=10)
            assert ReplayCommand.objects.get(client_command_id=data["client_command_id"]).state == "claimed"
        finally:
            finish.set()
        assert first.result(timeout=20)["state"] == "succeeded"
    assert BoxScan.objects.filter(request=env.request).count() == 1
    env.request.refresh_from_db()
    assert env.request.status == "issued"


def test_a_slow_stale_executor_cannot_commit_after_a_new_claim_succeeds(replay_env, monkeypatch):
    from datetime import timedelta
    from threading import Lock
    from django.utils import timezone
    from apps.audit.models import AuditLog
    env = replay_env
    assigned = envelope(env)
    assert prepare(env, assigned).status_code == execute(env, assigned).status_code == 200
    data = validated(envelope(env, "reviewed_issue", {"request_id": env.request.pk}))
    prepare_service(identity(env), data)
    from apps.evidence.storage import finalize_upload
    started, finish, mutex = Event(), Event(), Lock()
    attempts = 0
    def pause_first(photo, limit):
        nonlocal attempts
        with mutex:
            attempts += 1
            first = attempts == 1
        if first:
            started.set()
            assert finish.wait(10)
        return finalize_upload(photo, limit)
    monkeypatch.setattr("apps.hardware_requests.replay_execute.storage.finalize_upload", pause_first)
    who = identity(env)
    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(in_connection, execute_service, who, data)
        assert started.wait(10)
        try:
            ReplayCommand.objects.filter(client_command_id=data["client_command_id"]).update(
                claimed_at=timezone.now() - timedelta(minutes=6),
            )
            new = pool.submit(in_connection, execute_service, who, data)
            assert new.result(timeout=10)["state"] == "succeeded"
        finally:
            finish.set()
        with pytest.raises(ReplayFailure):
            old.result(timeout=10)
    command = ReplayCommand.objects.get(client_command_id=data["client_command_id"])
    assert command.state == "succeeded" and command.claim_attempts == 2
    assert AuditLog.objects.filter(action="request.issued").count() == 1
