from datetime import timedelta
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
from types import SimpleNamespace
import uuid

import pytest

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connections
from django.db.backends.base.base import BaseDatabaseWrapper
from django.test import SimpleTestCase
from django.utils import timezone

from apps.backup import archive_builder, compound_archive
from apps.backup.models import (
    BackupArchive,
    MakerspaceArchiveCustodyState,
    MakerspaceArchiveRecipient,
)
from apps.backup.main_projection_registry import (
    AUTO_CREATED_M2M_TABLES,
    RowDisposition,
    table_rules,
)
from apps.backup.main_projection_verification import build_expected_ledger
from apps.backup.postgres_client import client_binary
from apps.backup.projection_databases import restore_dump, temporary_database
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.recipients import fingerprint_for
from apps.events.models import Event, EventRegistration
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership


pytestmark = pytest.mark.django_db(transaction=True)

class _EveryDatabase(frozenset):
    """A `databases` allow-set that also admits aliases created after setup.

    Iteration still yields only the real aliases, so Django's teardown flushes
    exactly the databases it created.
    """

    def __contains__(self, alias):
        return True


def _guarded_test_case():
    """The TestCase whose undeclared-database guard is currently installed.

    Django closes over the test class when it patches `ensure_connection`, and
    that class attribute is the only place the allow-set can be widened.
    """
    patched = BaseDatabaseWrapper.ensure_connection
    for cell in patched.__closure__ or ():
        value = cell.cell_contents
        if isinstance(value, type) and issubclass(value, SimpleTestCase):
            return value
    return None


@pytest.fixture
def allow_projection_databases():
    """Let the readable-main projection open its short-lived databases.

    Django rejects connections to aliases that did not exist when the test class
    was set up, which is the right default. This projection creates, registers
    and drops a real database mid-test, and `databases="__all__"` cannot express
    that because it is snapshotted at setup. The allow-set is widened for the
    duration and restored before class teardown unwraps the guard.
    """
    case = _guarded_test_case()
    if case is None:
        yield
        return
    original = case.databases
    case.databases = _EveryDatabase(original)
    try:
        yield
    finally:
        case.databases = original

PLATFORM = "age1platform-e3"
TENANT_ONE = "age1tenant-e3-one"
TENANT_TWO = "age1tenant-e3-two"


def _archive():
    return BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        object_key=f"backup-archives/deployment/{uuid.uuid4()}.tar.age",
        expires_at=timezone.now() + timedelta(days=1),
    )


def _sovereign():
    space = Makerspace.objects.create(
        name="Sovereign E3",
        slug="sovereign-e3",
        superadmin_access_enabled=False,
    )
    for value in (TENANT_ONE, TENANT_TWO):
        MakerspaceArchiveRecipient.objects.create(
            makerspace=space,
            public_recipient=value,
            fingerprint=fingerprint_for(value),
            label="Tenant-held key",
            verified_at=timezone.now(),
        )
    MakerspaceArchiveCustodyState.objects.create(
        makerspace=space,
        state=MakerspaceArchiveCustodyState.State.HEALTHY,
    )
    return space


def _prepare(monkeypatch, settings):
    settings.BACKUP_AGE_RECIPIENT = PLATFORM
    require_binary = archive_builder._require_binary
    monkeypatch.setattr(
        archive_builder,
        "_require_binary",
        lambda command: None if command == "age" else require_binary(command),
    )
    monkeypatch.setattr(
        archive_builder,
        "_storage_modes",
        lambda: {"private": "versioned", "public_image": "versioned"},
    )
    commands = []
    real_run = archive_builder.subprocess.run

    def fake_age(command, **kwargs):
        if command[0] != "age":
            return real_run(command, **kwargs)
        commands.append(command)
        output = Path(command[command.index("-o") + 1])
        shutil.copyfile(command[-1], output)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(archive_builder.subprocess, "run", fake_age)
    return commands


def _authority_memberships(user):
    group = Group.objects.create(name=f"e3-group-{uuid.uuid4()}")
    content_type = ContentType.objects.get(
        app_label=InventoryProduct._meta.app_label,
        model=InventoryProduct._meta.model_name,
    )
    permission = Permission.objects.create(
        name="E3 retained permission",
        codename=f"e3_retained_{uuid.uuid4().hex}",
        content_type=content_type,
    )
    group.permissions.add(permission)
    user.groups.add(group)
    user.user_permissions.add(permission)
    return group, permission


def test_every_auto_created_m2m_table_has_an_explicit_disposition():
    discovered = {
        model._meta.db_table
        for model in django_apps.get_models(include_auto_created=True)
        if model._meta.auto_created and model._meta.managed
    }

    assert discovered == set(AUTO_CREATED_M2M_TABLES)
    assert all(
        disposition == RowDisposition.RETAIN_GLOBAL and predicate is None
        for disposition, predicate in AUTO_CREATED_M2M_TABLES.values()
    )
    assert {
        rule.model._meta.db_table
        for rule in table_rules()
        if rule.model._meta.auto_created
    } == discovered


def test_verification_ledger_digests_each_authority_through_table():
    user = get_user_model().objects.create_user(username="ledger-m2m-e3")
    _authority_memberships(user)

    ledger = build_expected_ledger("default", table_rules(), ())
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


def test_readable_main_excludes_sovereign_rows_and_keeps_global_and_ordinary(
    allow_projection_databases,
    monkeypatch, settings, tmp_path
):
    sovereign = _sovereign()
    ordinary = Makerspace.objects.create(name="Ordinary E3", slug="ordinary-e3")
    user = get_user_model().objects.create_user(username="deployment-global-e3")
    group, permission = _authority_memberships(user)
    MakerspaceMembership.objects.create(makerspace=sovereign, user=user)
    sovereign_product = InventoryProduct.objects.create(
        makerspace=sovereign, name="Sovereign tool", total_quantity=1
    )
    ordinary_product = InventoryProduct.objects.create(
        makerspace=ordinary,
        name="Ordinary tool",
        description="ordinary row must remain byte-for-byte represented",
        total_quantity=7,
        available_quantity=7,
    )
    event = Event.objects.create(
        makerspace=ordinary,
        title="Ordinary hosted event",
        starts_at=timezone.now(),
        ends_at=timezone.now() + timedelta(hours=1),
    )
    registration = EventRegistration.objects.create(
        event=event,
        name="Cross-boundary attendee",
        email="attendee@example.test",
        registered_via_makerspace=sovereign,
        payment_via_makerspace=sovereign,
    )
    sovereign_high_water = InventoryProduct.objects.create(
        makerspace=sovereign, name="Sovereign high-water tool", total_quantity=1
    )
    ordinary_expected = InventoryProduct.objects.values().get(pk=ordinary_product.pk)
    _prepare(monkeypatch, settings)

    encrypted, manifest, tempdir, _digest = archive_builder.build_archive(_archive())
    try:
        root = Path(tempdir.name, "bundle")
        assert (root / "manifest.json").is_file()
        assert (root / "database.dump").is_file()
        assert not (root / "main").exists()
        assert len(manifest["slices"]) == 1
        assert manifest["slices"][0]["makerspace_id"] == sovereign.pk
        assert manifest["excluded_makerspace_ids"] == [sovereign.pk]
        assert ordinary.pk in manifest["covered_makerspace_ids"]
        assert manifest["partial"] is True

        with temporary_database("e3_assert") as (using, database_name):
            restore_dump(root / "database.dump", database_name)
            assert not Makerspace.objects.using(using).filter(pk=sovereign.pk).exists()
            assert not InventoryProduct.objects.using(using).filter(
                pk=sovereign_product.pk
            ).exists()
            assert not InventoryProduct.objects.using(using).filter(
                pk=sovereign_high_water.pk
            ).exists()
            restored = InventoryProduct.objects.using(using).values().get(
                pk=ordinary_product.pk
            )
            assert restored == ordinary_expected
            restored_user = get_user_model().objects.using(using).get(pk=user.pk)
            assert restored_user.groups.filter(pk=group.pk).exists()
            assert restored_user.user_permissions.filter(pk=permission.pk).exists()
            assert Group.objects.using(using).get(pk=group.pk).permissions.filter(
                pk=permission.pk
            ).exists()
            restored_registration = EventRegistration.objects.using(using).get(
                pk=registration.pk
            )
            assert restored_registration.registered_via_makerspace_id is None
            assert restored_registration.payment_via_makerspace_id is None
            with connections[using].cursor() as cursor:
                cursor.execute(
                    "SELECT nextval(pg_get_serial_sequence(%s, %s))",
                    [InventoryProduct._meta.db_table, "id"],
                )
                assert cursor.fetchone()[0] > sovereign_high_water.pk
        slice_path = root / manifest["slices"][0]["path"]
        with tarfile.open(slice_path) as sealed_slice:
            handle = sealed_slice.extractfile("./inverse/boundary-deltas.json")
            assert handle is not None
            deltas = json.loads(handle.read())
        registration_deltas = {
            item["field"]: item["field_preimage"]
            for item in deltas
            if item["model"] == "events.EventRegistration"
            and item["row_pk"] == registration.pk
        }
        assert registration_deltas == {
            "registered_via_makerspace": sovereign.pk,
            "payment_via_makerspace": sovereign.pk,
        }
        with tarfile.open(encrypted) as outer:
            names = set(outer.getnames())
        assert "./manifest.json" in names
        assert "./database.dump" in names
    finally:
        tempdir.cleanup()


def test_readable_main_dump_holds_no_sovereign_plaintext(
    allow_projection_databases, monkeypatch, settings
):
    """The guarantee stated to customers, checked on the bytes that ship.

    The semantic test above proves the rows are gone once restored. This one
    reads the dump itself, because "excluded from the readable main" is a claim
    about the artifact an operator can open, not about a restored database. The
    ordinary product is the positive control: without it a passing assertion
    could just mean the scan never saw any product names at all.
    """
    sovereign = _sovereign()
    ordinary = Makerspace.objects.create(name="Ordinary E3 bytes", slug="ordinary-e3-bytes")
    InventoryProduct.objects.create(
        makerspace=sovereign, name="Sovereign secret widget", total_quantity=1
    )
    InventoryProduct.objects.create(
        makerspace=ordinary, name="Ordinary visible widget", total_quantity=1
    )
    _prepare(monkeypatch, settings)

    _encrypted, manifest, tempdir, _digest = archive_builder.build_archive(_archive())
    try:
        root = Path(tempdir.name, "bundle")
        # pg_restore to SQL text: the custom-format dump is compressed, so a raw
        # byte scan of the file would pass vacuously.
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
        # Visible metadata is expected to name the excluded tenant by id.
        assert manifest["excluded_makerspace_ids"] == [sovereign.pk]
    finally:
        tempdir.cleanup()


def test_missing_slice_fails_before_main_exclusion_or_outer_encryption(
    monkeypatch, settings
):
    sovereign = _sovereign()
    commands = _prepare(monkeypatch, settings)

    def omit_slice(self, **_kwargs):
        self.frozen_slices = (compound_archive.FrozenSlice(
            makerspace_id=sovereign.pk,
            slice_id=str(uuid.uuid4()),
            public_recipients=(TENANT_ONE, TENANT_TWO),
            recipient_fingerprints=(
                fingerprint_for(TENANT_ONE), fingerprint_for(TENANT_TWO)
            ),
            custody_state=MakerspaceArchiveCustodyState.State.HEALTHY,
        ),)
        self.expected_main_ledger = {}

    monkeypatch.setattr(
        compound_archive.CompoundCapture, "capture_from_snapshot", omit_slice
    )
    with pytest.raises(BackupBuildError, match="one verified slice"):
        archive_builder.build_archive(_archive())
    assert commands == []


def test_failed_plaintext_slice_verification_fails_before_sealing(
    monkeypatch, settings
):
    _sovereign()
    commands = _prepare(monkeypatch, settings)

    def fail_verification(*_args):
        raise BackupBuildError("injected plaintext verification failure")

    monkeypatch.setattr(
        compound_archive, "verify_unsealed_slice", fail_verification
    )
    with pytest.raises(BackupBuildError, match="plaintext verification failure"):
        archive_builder.build_archive(_archive())
    assert commands == []
