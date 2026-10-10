"""Resolution races use independent real PostgreSQL connections."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connections

from apps.audit.models import AuditLog
from apps.hardware_requests.models import ReplayCommand
from apps.hardware_requests.replay_recovery_service import ResolutionConflict, resolve_replay
from tests.hardware_requests.replay_helpers import replay_env
from tests.hardware_requests.recovery_helpers import failed_issue, successful_replacement

pytestmark = pytest.mark.django_db(transaction=True)


def review(user, pk, code, replacement=None):
    connections.close_all()
    try:
        return resolve_replay(user, pk, resolution_code=code, replacement_command_id=replacement).resolution_code
    except ResolutionConflict:
        return "conflict"
    finally:
        connections.close_all()


def test_competing_resolutions_commit_one_review_and_one_audit(replay_env):
    env = replay_env
    source = failed_issue(env)
    replacement = successful_replacement(env)
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(review, env.user, source.pk, "acknowledged_no_change"),
                 pool.submit(review, env.user, source.pk, "replaced_online", replacement.pk)]
        results = [call.result(timeout=20) for call in calls]
    assert results.count("conflict") == 1
    assert AuditLog.objects.filter(action="kiosk.replay_resolved").count() == 1


def test_one_success_cannot_resolve_two_concurrent_failures(replay_env):
    env = replay_env
    sources = [failed_issue(env), failed_issue(env)]
    replacement = successful_replacement(env)
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(review, env.user, source.pk, "replaced_online", replacement.pk) for source in sources]
        results = [call.result(timeout=20) for call in calls]
    assert sorted(results) == ["conflict", "replaced_online"]
    assert ReplayCommand.objects.filter(replacement_command=replacement).count() == 1
