"""Lane E section 11 row 3: capture/custody concurrency and revalidation."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import uuid

import pytest
from django.db import close_old_connections
from django.utils import timezone

from apps.backup import archive_payload, artifact_ledger, promotion
from apps.backup.models import (
    B1ActivationState,
    MakerspaceArchiveRecipient,
    PlatformBackupSettings,
)
from apps.backup.promotion_validation import validate_frozen_state
from apps.backup.recipient_states import compromise_recipient, revoke_recipient
from apps.backup.recipients import fingerprint_for
from apps.makerspaces.models import Makerspace
from tests.backup import test_compound_archive_e3 as e3
from tests.backup.test_promotion_e5 import _final_verified


pytestmark = pytest.mark.django_db(transaction=True)


class _ObjectPlan:
    def closure(self, _component):
        return {"private": {}, "public_image": {}}

    def bind_component(self, *_args):
        return None


class _SnapshotProbe:
    def __init__(self):
        self.frozen_slices = ()
        self.frozen_recipient_ids = ()

    def prepare_from_snapshot(self):
        self.frozen_recipient_ids = tuple(
            MakerspaceArchiveRecipient.objects.filter(
                verified_at__isnull=False,
                revoked_at__isnull=True,
                compromised_at__isnull=True,
            ).order_by("pk").values_list("pk", flat=True)
        )
        self.frozen_slices = (SimpleNamespace(makerspace_id=1),)

    def capture_from_snapshot(self, **_kwargs):
        return None


@pytest.mark.parametrize("phase", ("dump", "object-byte-capture"))
@pytest.mark.parametrize("custody_change", ("compromise", "revoke"))
def test_urgent_custody_change_commits_while_capture_phase_is_blocked(
    phase, custody_change, monkeypatch, tmp_path
):
    space = e3._sovereign()
    third_value = f"age1e10{uuid.uuid4().hex}"
    third = MakerspaceArchiveRecipient.objects.create(
        makerspace=space,
        public_recipient=third_value,
        fingerprint=fingerprint_for(third_value),
        label="E10 spare",
        verified_at=timezone.now(),
    )
    target = third if custody_change == "revoke" else (
        MakerspaceArchiveRecipient.objects.filter(makerspace=space).order_by("pk").first()
    )
    entered, release = Event(), Event()
    capture = _SnapshotProbe()
    root = tmp_path / "capture"
    root.mkdir()

    def block_here():
        entered.set()
        assert release.wait(10), "test did not release the simulated capture phase"

    def dump(path, _snapshot):
        if phase == "dump":
            block_here()
        path.write_bytes(b"frozen dump")

    def objects(*_args, **_kwargs):
        if phase == "object-byte-capture":
            block_here()
        return []

    monkeypatch.setattr(archive_payload, "_pg_dump", dump)
    monkeypatch.setattr(archive_payload, "_capture_objects", objects)
    monkeypatch.setattr(archive_payload, "_write_continuity_keys", lambda _path: None)
    monkeypatch.setattr(archive_payload, "_command_version", lambda _command: "pg_dump 16")
    monkeypatch.setattr(
        archive_payload, "build_object_ownership_plan", lambda *_args: _ObjectPlan()
    )

    def run_capture():
        close_old_connections()
        try:
            return archive_payload._snapshot_payload(
                e3._archive(), root, {"private": "versioned", "public_image": "versioned"},
                [], compound_capture=capture,
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_capture)
        assert entered.wait(10), f"capture never reached {phase}"
        if custody_change == "compromise":
            compromise_recipient(recipient=target)
        else:
            revoke_recipient(recipient=target)
        target.refresh_from_db()
        assert getattr(target, f"{custody_change}d_at") is not None
        assert not future.done(), "capture phase was released before the custody commit"
        release.set()
        future.result(timeout=10)

    assert target.pk in capture.frozen_recipient_ids


@pytest.mark.parametrize(
    "change", ("recipient_verified", "recipient_revoked", "recipient_compromised", "re_enable")
)
def test_every_post_snapshot_custody_change_aborts_promotion(change, tmp_path):
    space, recipient, archive, ledger, _size, _digest = _final_verified(tmp_path)
    if change == "recipient_verified":
        value = f"age1e10new{uuid.uuid4().hex}"
        MakerspaceArchiveRecipient.objects.create(
            makerspace=space,
            public_recipient=value,
            fingerprint=fingerprint_for(value),
            label="verified after snapshot",
            verified_at=timezone.now(),
        )
    elif change == "re_enable":
        space.superadmin_access_enabled = True
        space.save(update_fields=("superadmin_access_enabled", "updated_at"))
        B1ActivationState.objects.filter(makerspace=space).update(state="on")
    else:
        field = "revoked_at" if change.endswith("revoked") else "compromised_at"
        setattr(recipient, field, timezone.now())
        recipient.save(update_fields=(field,))

    with pytest.raises(artifact_ledger.ArtifactLedgerMismatch):
        promotion.promote_verified_artifact(ledger.pk)

    archive.refresh_from_db()
    ledger.refresh_from_db()
    assert archive.status == "running"
    assert ledger.state == "final_verified"


def test_newly_switched_off_tenant_after_snapshot_aborts_promotion():
    space = Makerspace.objects.create(
        name="E10 switch race", slug=f"e10-switch-{uuid.uuid4().hex}"
    )
    activation = B1ActivationState.objects.get(makerspace=space)
    frozen = {
        "makerspace_id": space.pk,
        "superadmin_access_enabled": True,
        "activation_state": "on",
        "custody_state": None,
        "recipients": [],
    }
    artifact_id = uuid.uuid4()
    artifact = SimpleNamespace(
        frozen_promotion_snapshot={"retained": [frozen]},
        outer_manifest={
            "makerspace_sets": {
                "retained": [space.pk],
                "readable_main": [space.pk],
                "sovereign": [],
            },
            "slice_components": [],
        },
        predecessor_success_at_snapshot=PlatformBackupSettings.load().last_success_at,
        predecessor_artifact_id_snapshot=None,
    )
    space.superadmin_access_enabled = False
    space.save(update_fields=("superadmin_access_enabled", "updated_at"))
    B1ActivationState.objects.filter(pk=activation.pk).update(state="off_pending")
    space.refresh_from_db()
    activation.refresh_from_db()

    with pytest.raises(artifact_ledger.ArtifactLedgerMismatch, match="access"):
        validate_frozen_state(
            artifact,
            {space.pk: space},
            (),
            {space.pk: activation},
            PlatformBackupSettings.load(),
            {artifact_id: artifact},
        )
