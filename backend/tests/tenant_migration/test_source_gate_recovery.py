import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.encryption.services import get_or_create_active_dek, rotate_dek
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.gate_errors import (
    SourceMigrationGateClosed,
    SourceMigrationRecoveryError,
)
from apps.tenant_migration.gate_locks import SOURCE_GATE_LOCK_NAMESPACE
from apps.tenant_migration.gate_runtime import tenant_write
from apps.tenant_migration.models import SourceMigrationGate
from apps.tenant_migration.source_gate import recover_expired
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.source_gate_helpers import (
    close_gate,
    make_actor,
    make_space,
)


pytestmark = pytest.mark.django_db(transaction=True)


def test_recovery_requires_expiry_no_lock_and_pre_cutover():
    actor = make_actor("recover")
    live_space = make_space("recover-live")
    close_gate(live_space, actor)
    with pytest.raises(SourceMigrationRecoveryError, match="live lease"):
        recover_expired(live_space, actor)

    expired_space = make_space("recover-expired")
    close_gate(expired_space, actor, expired=True)
    secondary = connections["default"].copy()
    try:
        with secondary.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)",
                [SOURCE_GATE_LOCK_NAMESPACE, expired_space.pk],
            )
            with pytest.raises(SourceMigrationRecoveryError, match="still held"):
                recover_expired(expired_space, actor)
            cursor.execute("ROLLBACK")
    finally:
        secondary.close()
    assert recover_expired(expired_space, actor) is not None
    recovered_gate = SourceMigrationGate.objects.get(makerspace=expired_space)
    assert recovered_gate.state == "open"
    assert recovered_gate.fencing_token == 2

    migrated = make_space("recover-migrated")
    close_gate(
        migrated, actor, state=SourceMigrationGate.State.MIGRATED_OUT, expired=True
    )
    with pytest.raises(SourceMigrationRecoveryError, match="signed target abort"):
        recover_expired(migrated, actor)


def test_declared_dek_rotation_exclusion_bypasses_closed_gate():
    actor = make_actor("dek-exclusion")
    space = make_space("dek-exclusion")
    with enabled_encryption():
        get_or_create_active_dek(space.pk)
    close_gate(space, actor)

    with transaction.atomic():
        with pytest.raises(SourceMigrationGateClosed):
            with tenant_write(space.pk):
                pass
    with enabled_encryption():
        assert rotate_dek(space.pk).key.version == 2


def test_tenant_purge_is_excluded_and_cascade_removes_its_gate(monkeypatch):
    actor = make_actor("purge-exclusion")
    space = make_space("purge-exclusion")
    space.archived_at = timezone.now()
    space.save(update_fields=["archived_at"])
    close_gate(space, actor)
    monkeypatch.setattr(
        "apps.makerspaces.lifecycle._delete_storage_keys", lambda _keys: None
    )
    monkeypatch.setattr(
        "apps.makerspaces.lifecycle._delete_public_image_keys", lambda _keys: None
    )

    lifecycle.purge(space, actor)

    assert not Makerspace.objects.filter(pk=space.pk).exists()
    assert not SourceMigrationGate.objects.filter(makerspace_id=space.pk).exists()


def test_recovery_command_requires_pre_cutover_state_and_audits_platform_scope():
    actor = make_actor("recover-command")
    space = make_space("recover-command")
    close_gate(space, actor, expired=True)

    call_command(
        "recover_source_migration_gate",
        makerspace=space.slug,
        actor=actor.username,
        yes=True,
    )

    event = AuditLog.objects.get(
        action="tenant_migration.source_gate_recovery_command"
    )
    assert event.makerspace_id is None
    assert event.meta["makerspace_id"] == space.pk
    assert event.meta["outcome"] == "reopened"

    migrated = make_space("recover-command-migrated")
    close_gate(
        migrated, actor, state=SourceMigrationGate.State.MIGRATED_OUT, expired=True
    )
    with pytest.raises(CommandError, match="signed target abort receipt"):
        call_command(
            "recover_source_migration_gate",
            makerspace=migrated.slug,
            actor=actor.username,
            yes=True,
        )
