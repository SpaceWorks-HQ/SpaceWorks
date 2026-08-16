from datetime import timedelta
from urllib.parse import unquote, urlparse

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup.models import ARCHIVE_PURGE_WARNING, BackupArchive
from apps.makerspaces.models import Makerspace, MakerspaceMembership


pytestmark = pytest.mark.django_db


def authenticated(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def manager_for(makerspace, username):
    actor = User.objects.create_user(username=username, access_status=User.AccessStatus.ACTIVE)
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return actor


def test_space_manager_can_request_only_their_tenant_archive(monkeypatch):
    own = Makerspace.objects.create(name="Own archive", slug="own-archive")
    other = Makerspace.objects.create(name="Other archive", slug="other-archive")
    manager = manager_for(own, "archive-manager")
    queued = []
    monkeypatch.setattr(
        "apps.backup.views_archives.run_backup_archive_task.delay", queued.append
    )

    own_url = reverse("admin-makerspace-backups", kwargs={"makerspace_id": own.pk})
    other_url = reverse("admin-makerspace-backups", kwargs={"makerspace_id": other.pk})
    response = authenticated(manager).post(own_url, {}, format="json")

    assert response.status_code == 202
    assert response.data["scope"] == BackupArchive.Scope.MAKERSPACE
    assert response.data["purge_warning"] == ARCHIVE_PURGE_WARNING
    assert queued == [response.data["id"]]
    assert authenticated(manager).get(other_url).status_code == 403
    assert AuditLog.objects.filter(action="backup.archive_requested").exists()


def test_deployment_archive_is_superadmin_only(monkeypatch):
    admin = User.objects.create_superuser(username="archive-super", password="secret")
    ordinary = User.objects.create_user(username="archive-ordinary")
    queued = []
    monkeypatch.setattr(
        "apps.backup.views_archives.run_backup_archive_task.delay", queued.append
    )
    url = reverse("admin-deployment-backups")

    assert authenticated(ordinary).post(url, {}, format="json").status_code == 403
    response = authenticated(admin).post(url, {}, format="json")
    assert response.status_code == 202
    assert response.data["scope"] == BackupArchive.Scope.DEPLOYMENT
    assert queued == [response.data["id"]]


def test_archive_download_token_is_bound_short_lived_and_single_use(monkeypatch):
    admin = User.objects.create_superuser(username="download-super", password="secret")
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        requested_by=admin,
        status=BackupArchive.Status.AVAILABLE,
        object_key="backup-archives/deployment/download.tar.age",
        age_encrypted=True,
        expires_at=timezone.now() + timedelta(days=1),
    )

    class Body:
        def iter_chunks(self):
            yield b"age-encrypted"

    monkeypatch.setattr("apps.backup.views_archives.storage.open_archive", lambda _key: Body())
    issue = authenticated(admin).post(
        reverse("admin-backup-download-url", kwargs={"archive_id": archive.pk})
    )
    token = unquote(urlparse(issue.data["url"]).path.rsplit("/", 1)[-1])
    path = reverse(
        "backup-archive-download",
        kwargs={"archive_id": archive.pk, "token": token},
    )

    assert issue.status_code == 200
    assert issue.data["purge_warning"] == ARCHIVE_PURGE_WARNING
    assert APIClient().get(path).status_code == 200
    assert APIClient().get(path).status_code == 404
