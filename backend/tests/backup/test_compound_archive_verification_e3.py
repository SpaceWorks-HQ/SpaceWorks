import json
from pathlib import Path
import subprocess
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.backup import archive_builder, compound_archive, compound_slice_build
from apps.backup.main_projection_registry import table_rules
from apps.backup.main_projection_verification import build_expected_ledger
from apps.backup.models import MakerspaceArchiveCustodyState
from apps.backup.postgres_client import client_binary
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.recipients import fingerprint_for
from apps.backup.source_sequence_reservations import sequence_facts
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from tests.backup import test_compound_archive_e3 as e3


pytestmark = pytest.mark.django_db(transaction=True)
allow_projection_databases = e3.allow_projection_databases


def test_verification_ledger_digests_each_authority_through_table():
    user = get_user_model().objects.create_user(username="ledger-m2m-e3")
    e3._authority_memberships(user)

    ledger = build_expected_ledger(
        "default", table_rules(), (), sequence_facts=sequence_facts("default")
    )
    through_models = (
        get_user_model()._meta.get_field("groups").remote_field.through,
        get_user_model()._meta.get_field("user_permissions").remote_field.through,
        Group._meta.get_field("permissions").remote_field.through,
    )
    for model in through_models:
        fact = ledger["tables"][model._meta.db_table]
        assert fact["count"] == model._base_manager.count()
        assert fact["count"] >= 1
        assert len(fact["identity_sha256"]) == 64
        assert len(fact["raw_rows_sha256"]) == 64


def test_readable_main_dump_holds_no_sovereign_plaintext(
    allow_projection_databases, monkeypatch, settings
):
    sovereign = e3._sovereign()
    ordinary = Makerspace.objects.create(
        name="Ordinary E3 bytes", slug="ordinary-e3-bytes"
    )
    InventoryProduct.objects.create(
        makerspace=sovereign, name="Sovereign secret widget", total_quantity=1
    )
    InventoryProduct.objects.create(
        makerspace=ordinary, name="Ordinary visible widget", total_quantity=1
    )
    e3._prepare(monkeypatch, settings)

    _encrypted, manifest, tempdir, _digest = archive_builder.build_archive(e3._archive())
    try:
        root = Path(tempdir.name, "bundle")
        readable = subprocess.run(
            [client_binary("pg_restore"), "--file=-", str(root / "database.dump")],
            capture_output=True,
            check=True,
        ).stdout
        assert b"Ordinary visible widget" in readable
        assert b"Sovereign secret widget" not in readable
        assert sovereign.name.encode() not in readable
        assert sovereign.slug.encode() not in readable

        outer_manifest = json.dumps(manifest).encode()
        assert b"Sovereign secret widget" not in outer_manifest
        assert manifest["excluded_makerspace_ids"] == [sovereign.pk]
    finally:
        tempdir.cleanup()


def test_missing_slice_fails_before_main_exclusion_or_outer_encryption(
    monkeypatch, settings
):
    sovereign = e3._sovereign()
    commands = e3._prepare(monkeypatch, settings)

    def omit_slice(self, **_kwargs):
        self.frozen_slices = (compound_archive.FrozenSlice(
            makerspace_id=sovereign.pk,
            slice_id=str(uuid.uuid4()),
            public_recipients=(e3.TENANT_ONE, e3.TENANT_TWO),
            recipient_fingerprints=(
                fingerprint_for(e3.TENANT_ONE), fingerprint_for(e3.TENANT_TWO)
            ),
            custody_state=MakerspaceArchiveCustodyState.State.HEALTHY,
        ),)
        self.expected_main_ledger = {}
        self.source_catalog_digest = "a" * 64

    monkeypatch.setattr(
        compound_archive.CompoundCapture, "capture_from_snapshot", omit_slice
    )
    with pytest.raises(BackupBuildError, match="one verified slice"):
        archive_builder.build_archive(e3._archive())
    assert commands == []


def test_failed_plaintext_slice_verification_fails_before_sealing(
    monkeypatch, settings
):
    e3._sovereign()
    commands = e3._prepare(monkeypatch, settings)

    def fail_verification(*_args, **_kwargs):
        raise BackupBuildError("injected plaintext verification failure")

    monkeypatch.setattr(
        compound_slice_build, "verify_unsealed_slice", fail_verification
    )
    with pytest.raises(BackupBuildError, match="plaintext verification failure"):
        archive_builder.build_archive(e3._archive())
    assert commands == []
