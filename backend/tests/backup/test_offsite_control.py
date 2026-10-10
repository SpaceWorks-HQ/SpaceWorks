"""Control-plane forms and actions share the destination API's security rules."""

import json

import pytest
from django.contrib.admin import AdminSite
from django.test import RequestFactory

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup.admin_offsite import (
    BackupDestinationAdmin, BackupDestinationForm, BackupDestinationUploadAdmin,
)
from apps.backup.models import BackupDestination, BackupDestinationUpload
from tests.backup.offsite_test_support import make_destination

pytestmark = pytest.mark.django_db


def _data(**overrides):
    return {
        "name": "control-cold", "endpoint_url": "https://s3.example.test", "bucket": "cold",
        "region": "us-east-1", "prefix": "/archives/", "addressing_style": "path",
        "enabled": True, "retention_days": 30, "new_access_key_id": "control-access",
        "new_secret_access_key": "control-secret", **overrides,
    }


def _request(*, superadmin=True):
    request = RequestFactory().get("/control/backup/backupdestination/")
    factory = User.objects.create_superuser if superadmin else User.objects.create_user
    request.user = factory(username="control-admin" if superadmin else "control-member", password="x")
    return request


def test_control_create_and_rotation_encrypt_credentials_and_never_prefill_passwords():
    request = _request()
    model_admin = BackupDestinationAdmin(BackupDestination, AdminSite())
    form = BackupDestinationForm(data=_data())
    assert form.is_valid(), form.errors
    destination = form.save(commit=False)
    model_admin.save_model(request, destination, form, change=False)
    destination.refresh_from_db()
    assert destination.prefix == "archives"
    assert destination.created_by_id == request.user.pk
    assert destination.get_secret_access_key() == "control-secret"
    assert destination.secret_access_key.startswith("fernet:")
    form_class = model_admin.get_form(request, destination)
    unbound = form_class(instance=destination)
    assert "access_key_id" not in unbound.fields and "secret_access_key" not in unbound.fields
    assert "control-secret" not in unbound.as_p()
    assert destination.secret_access_key not in unbound.as_p()
    rotation = BackupDestinationForm(instance=destination, data=_data(new_secret_access_key="rotated-secret"))
    assert rotation.is_valid(), rotation.errors
    model_admin.save_model(request, rotation.save(commit=False), rotation, change=True)
    destination.refresh_from_db()
    assert destination.get_secret_access_key() == "rotated-secret"
    for entry in AuditLog.objects.filter(action__startswith="backup.destination_"):
        assert entry.actor_id == request.user.pk
        assert "control-secret" not in json.dumps(entry.meta)
        assert "rotated-secret" not in json.dumps(entry.meta)


@pytest.mark.parametrize("overrides", [
    {"prefix": "archives/../escape"}, {"endpoint_url": "ftp://example.test"},
    {"new_secret_access_key": ""}, {"retention_days": 0},
])
def test_control_form_validates_the_same_boundaries_as_the_api(overrides):
    assert not BackupDestinationForm(data=_data(**overrides)).is_valid()


def test_control_test_and_retire_actions_use_audited_lifecycle_services(monkeypatch):
    request = _request()
    destination = make_destination("cold")
    model_admin = BackupDestinationAdmin(BackupDestination, AdminSite())
    monkeypatch.setattr(model_admin, "message_user", lambda *args, **kwargs: None)
    probes = []
    monkeypatch.setattr("apps.backup.offsite_client.probe",
                        lambda destination, **kwargs: probes.append(destination.pk))
    rows = BackupDestination.objects.filter(pk=destination.pk)

    model_admin.test_destinations(request, rows)
    model_admin.retire_destinations(request, rows)

    assert probes == [destination.pk]
    destination.refresh_from_db()
    assert destination.retired_at and not destination.enabled
    assert not destination.access_key_id and not destination.secret_access_key
    assert AuditLog.objects.get(action="backup.destination_probed").actor_id == request.user.pk
    assert AuditLog.objects.get(action="backup.destination_retired").actor_id == request.user.pk
    assert not BackupDestinationForm(instance=destination, data=_data()).is_valid()


def test_control_destination_is_superadmin_only_and_journal_is_read_only():
    request = _request(superadmin=False)
    destinations = BackupDestinationAdmin(BackupDestination, AdminSite())
    assert not destinations.has_module_permission(request)
    assert not destinations.has_add_permission(request)
    assert not destinations.has_change_permission(request)
    assert not destinations.has_delete_permission(request)
    request.user = User.objects.create_superuser(username="journal-admin", password="x")
    journal = BackupDestinationUploadAdmin(BackupDestinationUpload, AdminSite())
    assert journal.has_view_permission(request)
    assert not journal.has_add_permission(request)
    assert not journal.has_change_permission(request)
    assert not journal.has_delete_permission(request)
