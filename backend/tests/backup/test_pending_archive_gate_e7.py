from types import SimpleNamespace
import uuid

import pytest

from apps.backup.archive_builder import build_archive
from apps.backup.models import BackupArchive
from apps.backup.not_restored import TenantNotRestored
from tests.backup.e7_reservation_test_helpers import persist_restore_state


pytestmark = pytest.mark.django_db(transaction=True)


def test_deployment_backup_refuses_to_treat_pending_tenants_as_absent():
    makerspace_id = 8000 + uuid.uuid4().int % 1000
    persist_restore_state(
        {"component_ids": [str(uuid.uuid4())]},
        makerspace_id=makerspace_id,
    )
    archive = SimpleNamespace(
        scope=BackupArchive.Scope.DEPLOYMENT,
        makerspace_id=None,
    )

    with pytest.raises(TenantNotRestored):
        build_archive(archive)


def test_tenant_backup_refuses_a_pending_snapshot_identity():
    makerspace_id = 9000 + uuid.uuid4().int % 1000
    persist_restore_state(
        {"component_ids": [str(uuid.uuid4())]},
        makerspace_id=makerspace_id,
    )
    archive = SimpleNamespace(
        scope=BackupArchive.Scope.MAKERSPACE,
        makerspace_id=makerspace_id,
    )

    with pytest.raises(TenantNotRestored):
        build_archive(archive)
