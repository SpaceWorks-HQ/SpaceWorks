import pytest

from apps.backup.host_supervisor import HostMarkerTransition
from apps.tenant_migration.tenant_restore_orchestrator import run_target_restore
from apps.tenant_migration.tenant_restore_types import RestoreInputs, TenantRestoreRefused
from tests.tenant_migration import test_tenant_restore_order_d7 as fixtures


def _run(tmp_path, database, pointer, target, *, scheduler=None):
    return run_target_restore(
        ops_dir=tmp_path / "ops",
        inputs=RestoreInputs(
            fixtures.RUN_ID,
            fixtures.ARTIFACT,
            fixtures.CAPTURE_ID,
            "admin@example.test",
        ),
        artifact=fixtures.Artifact(),
        database=database,
        writers=database.writers,
        pointer=pointer,
        target=target,
        object_store=fixtures.Objects(),
        destination_prefix="imports/run",
        capability_journal=fixtures.Journal(),
        marker_writer=HostMarkerTransition(
            tmp_path / "marker.json", fixtures.Journal(), require_root_owned=False
        ),
        scheduler=scheduler,
        require_root_owned=False,
    )


def test_activation_verification_failure_keeps_target_non_normal_and_writers_stopped(
    tmp_path
):
    events = []
    writers = fixtures.Writers(events, tmp_path / "ops")
    database = fixtures.Database(writers, events)
    pointer = fixtures.Pointer(events)

    class FailingTarget(fixtures.Target):
        def verify_activation(self, _sibling, _inputs):
            self.events.append("activation-verification-failed")
            raise TenantRestoreRefused("D8 activation verification failed")

    with pytest.raises(TenantRestoreRefused, match="activation verification"):
        _run(tmp_path, database, pointer, FailingTarget(pointer, events))

    assert "activation-verification-failed" in events
    assert "cutover" not in events
    assert "normal" not in events
    assert "clear-host-gate" not in events
    assert "start" not in events


@pytest.mark.parametrize("scheduler_declared", (False, True))
def test_scheduler_mode_and_callback_presence_must_agree_before_any_mutation(
    tmp_path, scheduler_declared
):
    events = []
    writers = fixtures.Writers(events, tmp_path / "ops")
    database = fixtures.Database(writers, events)
    pointer = fixtures.Pointer(events)
    original = pointer.preflight

    def preflight(**kwargs):
        facts = original(**kwargs)
        mode = "external" if not scheduler_declared else "image"
        return facts.__class__(
            facts.adapter_supported,
            facts.pointer_compare_and_swap,
            facts.exact_current_identity,
            mode,
            facts.cloud_config_digest_matches,
            facts.static_config_initialized,
            facts.complete_writer_set,
        )

    pointer.preflight = preflight
    scheduler = object() if scheduler_declared else None

    with pytest.raises(TenantRestoreRefused, match="callback adapter declaration"):
        _run(
            tmp_path,
            database,
            pointer,
            fixtures.Target(pointer, events),
            scheduler=scheduler,
        )

    assert events == []
