"""Destination API pagination, credential rotation, dispatch and authority contracts."""

import json
import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup.models import BackupArchive, BackupDestinationUpload
from tests.backup.offsite_test_support import make_destination

pytestmark = pytest.mark.django_db


def _client(*, superadmin=True):
    factory = User.objects.create_superuser if superadmin else User.objects.create_user
    actor = factory(username=f"surface-{uuid.uuid4().hex}", password="x")
    client = APIClient()
    client.force_authenticate(actor)
    return actor, client


def _upload(destination):
    now = timezone.now()
    return BackupDestinationUpload.objects.create(
        destination=destination, archive_id_snapshot=uuid.uuid4(),
        scope_snapshot="deployment", archive_completed_at_snapshot=now,
        expected_size_bytes=10, expected_sha256="a" * 64, integrity_source="archive_row",
        remote_locator=f"remote/{uuid.uuid4()}", next_attempt_at=now,
        expires_at=now + timedelta(days=30),
    )


def test_destination_list_is_paginated_and_rotated_credentials_stay_write_only():
    actor, client = _client()
    destinations = [make_destination("cold", name=f"cold-{i:02}") for i in range(25)]
    url = reverse("admin-backup-destinations")
    first = client.get(url)
    assert first.status_code == 200
    assert first.data["count"] == 25 and len(first.data["results"]) == 24
    assert first.data["next"] and first.data["previous"] is None
    second = client.get(url, {"page": 2})
    assert len(second.data["results"]) == 1 and second.data["next"] is None
    destination = destinations[0]
    response = client.patch(
        reverse("admin-backup-destination", args=[destination.pk]),
        {"access_key_id": "rotated-access", "secret_access_key": "rotated-secret"},
        format="json",
    )
    assert response.status_code == 200
    destination.refresh_from_db()
    assert destination.get_access_key_id() == "rotated-access"
    assert destination.get_secret_access_key() == "rotated-secret"
    assert destination.secret_access_key.startswith("fernet:")
    detail = client.get(reverse("admin-backup-destination", args=[destination.pk]))
    assert detail.data["credentials_set"] is True
    for body in (first.data, response.data, detail.data):
        assert "secret_access_key" not in json.dumps(body)
        assert "access_key_id" not in json.dumps(body)
    entry = AuditLog.objects.get(action="backup.destination_updated")
    assert entry.actor_id == actor.pk
    assert "rotated-secret" not in json.dumps(entry.meta)


def test_journal_pages_reach_beyond_the_old_hundred_row_cutoff_and_are_destination_scoped():
    _, client = _client()
    destination = make_destination("cold")
    other = make_destination("other")
    rows = [_upload(destination) for _ in range(101)]
    _upload(other)
    url = reverse("admin-backup-destination-uploads", args=[destination.pk])
    seen = set()
    for page in range(1, 6):
        response = client.get(url, {"page": page})
        assert response.status_code == 200 and response.data["count"] == 101
        seen.update(row["id"] for row in response.data["results"])
        assert all(row["destination"] == destination.name for row in response.data["results"])
    assert seen == {row.pk for row in rows}
    assert client.get(url, {"page": 6}).status_code == 404


@pytest.mark.parametrize("name, method, needs_id", [
    ("admin-backup-destinations", "get", False),
    ("admin-backup-destinations", "post", False),
    ("admin-backup-destination", "get", True),
    ("admin-backup-destination", "patch", True),
    ("admin-backup-destination-retire", "post", True),
    ("admin-backup-destination-probe", "post", True),
    ("admin-backup-destination-uploads", "get", True),
    ("admin-backup-destination-push", "post", False),
])
def test_every_destination_surface_refuses_non_superadmins(name, method, needs_id):
    _, client = _client(superadmin=False)
    destination = make_destination("cold")
    url = reverse(name, args=[destination.pk] if needs_id else [])
    assert getattr(client, method)(url).status_code == 403
    assert not AuditLog.objects.filter(action__startswith="backup.destination_").exists()


def test_retired_destinations_cannot_be_reenabled_or_tested_and_keep_the_journal():
    actor, client = _client()
    destination = make_destination("cold")
    upload = _upload(destination)
    retire = reverse("admin-backup-destination-retire", args=[destination.pk])
    assert client.post(retire).status_code == 200
    assert client.post(retire).status_code == 400
    assert client.patch(reverse("admin-backup-destination", args=[destination.pk]),
                        {"enabled": True}, format="json").status_code == 400
    assert client.post(reverse("admin-backup-destination-probe", args=[destination.pk])).status_code == 404
    upload.refresh_from_db()
    assert upload.destination_id == destination.pk
    entry = AuditLog.objects.get(action="backup.destination_retired")
    assert entry.actor_id == actor.pk


@pytest.mark.parametrize("dispatched", [True, False])
def test_manual_push_reports_dispatch_failure_and_audits_the_request(monkeypatch, dispatched):
    actor, client = _client()
    monkeypatch.setattr("apps.backup.views_offsite.dispatch_offsite_push", lambda: dispatched)
    response = client.post(reverse("admin-backup-destination-push"))
    assert response.status_code == (202 if dispatched else 503)
    assert AuditLog.objects.get(action="backup.offsite_push_requested").actor_id == actor.pk


@pytest.mark.parametrize("dispatch_fails", [False, True])
def test_rehydration_api_dispatches_an_admitted_request_and_audits_user(monkeypatch, dispatch_fails):
    actor, client = _client()
    archive = BackupArchive.objects.create(scope="deployment", object_key=f"backup/{uuid.uuid4()}")
    destination = make_destination("cold")
    calls = []
    monkeypatch.setattr("apps.backup.views_offsite.validate_rehydration", lambda *args: None)

    def dispatch(*args):
        calls.append(args)
        if dispatch_fails:
            raise RuntimeError("broker down")

    monkeypatch.setattr("apps.backup.views_offsite.rehydrate_backup_archive_task.delay", dispatch)
    response = client.post(reverse("admin-backup-archive-rehydrate", args=[archive.pk]),
                           {"destination": destination.pk}, format="json")
    assert response.status_code == (503 if dispatch_fails else 202)
    assert calls == [(str(archive.pk), destination.pk, actor.pk)]
    assert AuditLog.objects.get(action="backup.archive_rehydrate_requested").actor_id == actor.pk


def test_destination_location_cannot_move_after_journaling_but_credentials_can_rotate():
    _, client = _client()
    destination = make_destination("cold")
    _upload(destination)
    url = reverse("admin-backup-destination", args=[destination.pk])
    for payload in ({"bucket": "other"}, {"endpoint_url": "https://other.example.test"},
                    {"prefix": "new-prefix"}):
        assert client.patch(url, payload, format="json").status_code == 400
    response = client.patch(url, {"secret_access_key": "new-secret", "enabled": False}, format="json")
    assert response.status_code == 200
    destination.refresh_from_db()
    assert destination.get_secret_access_key() == "new-secret"
    assert destination.bucket == "cold"


def test_probe_turns_unreadable_credentials_into_a_safe_audited_error():
    actor, client = _client()
    destination = make_destination("cold")
    destination.secret_access_key = "fernet:invalid-ciphertext"
    destination.save()
    response = client.post(reverse("admin-backup-destination-probe", args=[destination.pk]))
    assert response.status_code == 200
    assert response.data == {"ok": False, "error_code": "credentials_unreadable"}
    entry = AuditLog.objects.get(action="backup.destination_probed")
    assert entry.actor_id == actor.pk
    assert "invalid-ciphertext" not in json.dumps(entry.meta)
