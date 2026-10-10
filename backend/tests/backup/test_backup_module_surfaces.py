"""All module-off tenant routes deny before side effects; custody stays scoped."""

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup.models import (
    BackupArchive, MakerspaceArchiveCustodyState, MakerspaceArchiveRecipient,
    MakerspaceTenantExitCustodyState,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.module_install import uninstall_module
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.module_registry import core_module_keys

pytestmark = pytest.mark.django_db


def _client(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def test_module_off_refuses_every_tenant_mutation_before_processing_payloads():
    actor = User.objects.create_superuser(username="module-off-all", password="x")
    space = Makerspace.objects.create(name="Off", slug="backup-off-all", enabled_modules=sorted(core_module_keys()))
    recipient = MakerspaceArchiveRecipient.objects.create(
        makerspace=space, public_recipient="age1test", fingerprint="a" * 64, label="test",
    )
    archive = BackupArchive.objects.create(
        makerspace=space, scope="makerspace", superadmin_access_at_decision=True,
        object_key=f"backup/{uuid.uuid4()}", status="available", expires_at=timezone.now() + timedelta(days=1),
    )
    client = _client(actor)
    routes = [reverse("admin-makerspace-backups", args=[space.pk]),
              reverse("admin-archive-recipient-list-create", args=[space.pk]),
              reverse("admin-backup-download-url", args=[archive.pk])]
    routes += [reverse(f"admin-archive-recipient-{action}", args=[space.pk, recipient.pk])
               for action in ("verify", "reissue", "revoke", "reactivate")]
    for url in routes:
        response = client.post(url, {}, format="json")
        assert response.status_code == 400, (url, response.data)
        assert "backup" in str(response.data)
    assert not AuditLog.objects.filter(action__startswith="backup.").exists()
    archive.refresh_from_db()
    assert not archive.download_token_digest
    recipient.refresh_from_db()
    assert recipient.revoked_at is None and recipient.verified_at is None


def test_custody_exposes_both_states_only_to_the_makerspace_manager():
    space = Makerspace.objects.create(name="Own", slug="custody-own")
    foreign = Makerspace.objects.create(name="Foreign", slug="custody-foreign")
    actor = User.objects.create_user(username="custody-manager")
    MakerspaceMembership.objects.create(user=actor, makerspace=space, role="space_manager")
    MakerspaceArchiveCustodyState.objects.update_or_create(
        makerspace=space, defaults={"state": "not_applicable", "reason_code": "platform_access"},
    )
    MakerspaceTenantExitCustodyState.objects.update_or_create(
        makerspace=space, defaults={"state": "degraded_one_recipient", "reason_code": "one_recipient"},
    )
    client = _client(actor)
    response = client.get(reverse("admin-makerspace-backup-custody", args=[space.pk]))
    assert response.status_code == 200
    assert response.data["archive_custody"]["state"] == "not_applicable"
    assert response.data["tenant_exit_custody"]["state"] == "degraded_one_recipient"
    assert client.get(reverse("admin-makerspace-backup-custody", args=[foreign.pk])).status_code == 403


def test_module_purge_cleans_failed_attempt_prefix_after_commit(monkeypatch):
    actor = User.objects.create_superuser(username="purge-staging", password="x")
    space = Makerspace.objects.create(name="Purge", slug="purge-staging")
    attempt = f"backup-archives/staging/{uuid.uuid4()}/attempt.tar.age"
    archive = BackupArchive.objects.create(
        makerspace=space, scope="makerspace", superadmin_access_at_decision=True,
        object_key=f"backup/{uuid.uuid4()}", staging_object_key=attempt, status="failed",
    )
    keys, prefixes = [], []
    monkeypatch.setattr("apps.makerspaces.module_purge._delete_private_keys",
                        lambda values: keys.extend(values) or set(values))
    monkeypatch.setattr("apps.backup.storage.delete_archive_prefix",
                        lambda prefix: prefixes.append(prefix) or True)
    uninstall_module(space, "backup")
    # django_db's enclosing transaction never commits, so explicitly execute only
    # the callback captured from this purge, as Django's admin tests do.
    from django.test import TestCase
    with TestCase.captureOnCommitCallbacks(execute=True):
        counts = purge_module(space, "backup", actor)
        assert prefixes == []
    assert counts["backup_archives"] == 1
    assert set(keys) == {archive.object_key, attempt, f"backup-archives/staging/{archive.pk}.tar.age"}
    assert prefixes == [f"backup-archives/staging/{archive.pk}/"]
