"""The `backup` module key: tenant surfaces gated, platform and security paths never."""

import importlib
import uuid

import pytest
from django.apps import apps as django_apps
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.backup.activation import ActivationModuleRequiredError, set_superadmin_access
from apps.backup.custody import with_makerspace_custody_lock
from apps.backup.models import BackupArchive, MakerspaceArchiveRecipient
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_install import ModuleInstallError, uninstall_module
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.module_registry import core_module_keys

pytestmark = pytest.mark.django_db


def _space(slug, *, backup=True):
    modules = set(core_module_keys()) | ({"backup"} if backup else set())
    return Makerspace.objects.create(name=slug, slug=slug, enabled_modules=sorted(modules))


def _super():
    return User.objects.create_superuser(username=f"bk-{uuid.uuid4().hex[:6]}", password="x")


def _client(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def _recipient(space):
    return MakerspaceArchiveRecipient.objects.create(
        makerspace=space, public_recipient=f"age1{uuid.uuid4().hex}",
        fingerprint=uuid.uuid4().hex * 2, label="key", verified_at=timezone.now(),
    )


def test_module_off_refuses_tenant_surfaces_with_400_naming_the_key():
    space = _space("bk-off", backup=False)
    client = _client(_super())
    for url in (
        reverse("admin-makerspace-backups", args=[space.pk]),
        reverse("admin-archive-recipient-list-create", args=[space.pk]),
        reverse("admin-makerspace-backup-custody", args=[space.pk]),
    ):
        response = client.get(url)
        assert response.status_code == 400, url
        assert "backup" in str(response.data)


def test_compromise_is_never_module_gated():
    space = _space("bk-compromise", backup=False)
    recipient = _recipient(space)
    response = _client(_super()).post(
        reverse("admin-archive-recipient-compromise", args=[space.pk, recipient.pk])
    )
    assert response.status_code == 200, response.data
    recipient.refresh_from_db()
    assert recipient.compromised_at is not None


def test_deployment_backups_are_never_module_gated(monkeypatch):
    _space("bk-deploy-off", backup=False)
    monkeypatch.setattr("apps.backup.views_archives.run_backup_archive_task.delay", lambda _id: None)
    response = _client(_super()).post(reverse("admin-deployment-backups"), {}, format="json")
    assert response.status_code == 202


def test_custody_endpoint_reports_both_custody_states():
    space = _space("bk-custody")
    response = _client(_super()).get(reverse("admin-makerspace-backup-custody", args=[space.pk]))
    assert response.status_code == 200
    assert response.data["superadmin_access_enabled"] is True
    assert response.data["verified_recipient_count"] == 0


def test_uninstall_refused_while_superadmin_access_is_off():
    space = _space("bk-sovereign")
    Makerspace.objects.filter(pk=space.pk).update(superadmin_access_enabled=False)
    with pytest.raises(ModuleInstallError, match="superadmin access is disabled"):
        uninstall_module(space, "backup")
    space.refresh_from_db()
    assert "backup" in space.enabled_modules


def test_switch_off_refused_without_the_module():
    space = _space("bk-switch", backup=False)
    _recipient(space)
    _recipient(space)
    with pytest.raises(ActivationModuleRequiredError):
        with with_makerspace_custody_lock(space.pk) as custody:
            set_superadmin_access(custody, enabled=False, actor=None)
    space.refresh_from_db()
    assert space.superadmin_access_enabled is True


def test_purge_deletes_only_ad_hoc_tenant_archives(monkeypatch):
    from apps.backup.models import BackupRun

    space = _space("bk-purge")
    run = BackupRun.objects.create(cohort_at=timezone.now(), flag_snapshot={}, holder=uuid.uuid4())
    common = dict(
        scope=BackupArchive.Scope.MAKERSPACE, makerspace=space, superadmin_access_at_decision=True,
        status=BackupArchive.Status.FAILED,
    )
    ad_hoc = BackupArchive.objects.create(object_key=f"k/{uuid.uuid4()}", **common)
    run_made = BackupArchive.objects.create(object_key=f"k/{uuid.uuid4()}", backup_run=run, **common)
    recipient = _recipient(space)
    deleted_keys = []
    monkeypatch.setattr(
        "apps.makerspaces.module_purge._delete_private_keys",
        lambda keys: deleted_keys.extend(keys) or set(keys),
    )
    uninstall_module(space, "backup")

    counts = purge_module(space, "backup", _super())

    assert counts["backup_archives"] == 1
    assert not BackupArchive.objects.filter(pk=ad_hoc.pk).exists()
    assert BackupArchive.objects.filter(pk=run_made.pk).exists()
    assert MakerspaceArchiveRecipient.objects.filter(pk=recipient.pk).exists()
    assert deleted_keys == [ad_hoc.object_key]


def test_backfill_migration_adds_the_key_to_existing_rows():
    space = _space("bk-backfill", backup=False)
    migration = importlib.import_module("apps.backup.migrations.0026_backfill_backup_module")
    migration.enable_backup_module(django_apps, None)
    space.refresh_from_db()
    assert "backup" in space.enabled_modules
