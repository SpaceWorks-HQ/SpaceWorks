import pytest

from apps.backup.custody import initialize_custody_state
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import ReplayCommand
from apps.makerspaces import lifecycle
from tests.hardware_requests.replay_helpers import replay_env
from tests.hardware_requests.recovery_helpers import failed_issue, resolve, staff_client, successful_replacement

pytestmark = pytest.mark.django_db(transaction=True)


def test_whole_tenant_purge_clears_protected_resolution_link_before_domain_rows(replay_env, monkeypatch):
    env = replay_env
    initialize_custody_state(env.space.pk)
    env.user.is_superuser = True
    env.user.save(update_fields=["is_superuser"])
    failure = failed_issue(env)
    replacement = successful_replacement(env)
    assert resolve(staff_client(env.user), failure, "replaced_online", replacement).status_code == 200
    monkeypatch.setattr(lifecycle, "_delete_storage_keys", lambda keys: None)
    lifecycle.purge(lifecycle.archive(env.space, env.user), env.user)
    assert not ReplayCommand.objects.filter(pk__in=[failure.pk, replacement.pk]).exists()
    assert not EvidencePhoto.objects.filter(pk=failure.evidence_id).exists()
