from io import BytesIO
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from apps.machines import service_storage
from apps.machines.models import Machine, MachineServiceRequest, MachineType, ServiceRequestFile
from apps.machines.service_file_policies import get_policy
from apps.machines.service_workflow import submit
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import authenticated_client, make_member, make_space


pytestmark = pytest.mark.django_db


def service_request(space):
    kind = MachineType.objects.create(
        makerspace=space, slug=f"service-file-{uuid4().hex[:8]}", name="Service file type"
    )
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Laser")
    member = make_member(f"service-file-member-{uuid4().hex[:8]}", space)
    return submit(
        machine, member, title="Repair", requester_name="Member",
        contact_email=member.email, contact_phone="123",
    ), machine


def manager(space):
    return make_member(
        f"service-file-manager-{uuid4().hex[:8]}", space,
        MakerspaceMembership.Role.MACHINE_MANAGER,
    )


def request_url(row, action):
    return reverse(f"admin-machine-service-file-{action}", kwargs={"pk": row.pk})


def fake_result(size=4, content_type="application/pdf"):
    return service_storage.ServiceObjectValidationResult(size=size, content_type=content_type)


def test_presign_finalize_happy_path_and_no_key_leak(monkeypatch):
    space = make_space("service-file-happy")
    row, _ = service_request(space)
    client = authenticated_client(manager(space))
    monkeypatch.setattr(service_storage, "presigned_upload", lambda *args: {"url": "https://upload.test"})

    presign = client.post(request_url(row, "presign"), {"filename": "report.pdf", "content_type": "application/pdf"}, format="json")
    file_id = presign.data["file_id"]
    monkeypatch.setattr(service_storage, "finalize_upload", lambda *args: 4)
    monkeypatch.setattr(service_storage, "validate_service_object", lambda *args: fake_result())
    finalized = client.post(request_url(row, "finalize"), {"file_id": file_id}, format="json")

    file = ServiceRequestFile.objects.get(pk=file_id)
    assert (presign.status_code, finalized.status_code) == (201, 201)
    assert file.service_request_id == row.pk and file.attached_at is not None
    assert "object_key" not in str(presign.data)


def test_declared_type_size_and_signature_rejections(monkeypatch):
    space = make_space("service-file-invalid")
    row, _ = service_request(space)
    client = authenticated_client(manager(space))
    monkeypatch.setattr(service_storage, "presigned_upload", lambda *args: {"url": "https://upload.test"})

    invalid = client.post(request_url(row, "presign"), {"filename": "malware.exe", "content_type": "application/pdf"}, format="json")
    presign = client.post(request_url(row, "presign"), {"filename": "report.pdf", "content_type": "application/pdf"}, format="json")
    monkeypatch.setattr(service_storage, "finalize_upload", lambda *args: 0)
    oversized = client.post(request_url(row, "finalize"), {"file_id": presign.data["file_id"]}, format="json")

    upload = ServiceRequestFile.objects.get(pk=presign.data["file_id"])
    class Client:
        def head_object(self, **kwargs): return {"ContentLength": 4}
        def get_object(self, **kwargs): return {"Body": BytesIO(b"nope"), "ContentType": "application/pdf"}
    monkeypatch.setattr(service_storage, "_client", lambda: Client())
    with pytest.raises(ValidationError):
        service_storage.validate_service_object(upload, get_policy("documents", 1))

    assert (invalid.status_code, oversized.status_code) == (400, 400)


def test_put_attach_failure_compensates_final_object(monkeypatch, settings):
    settings.STORAGE_PRESIGN_METHOD = "put"
    space = make_space("service-file-put")
    row, machine = service_request(space)
    actor = manager(space)
    file = ServiceRequestFile.objects.create(
        machine=machine, kind="attachment", object_key="machine/key", content_type="application/pdf",
        original_filename="report.pdf", owner_user_id=actor.pk,
    )
    monkeypatch.setattr(service_storage, "finalize_upload", lambda *args: 4)
    monkeypatch.setattr(service_storage, "validate_service_object", lambda *args: fake_result())
    monkeypatch.setattr("apps.machines.service_storage.limits.add_storage", Mock(side_effect=ValidationError("quota")))
    cleanup = Mock()
    monkeypatch.setattr(service_storage, "cleanup_upload", cleanup)

    with pytest.raises(ValidationError):
        service_storage.finalize_file(row, file_id=file.pk, actor=actor)
    cleanup.assert_called_once_with(file.object_key)
    assert ServiceRequestFile.objects.get(pk=file.pk).service_request_id is None


def test_finalize_refuses_another_users_staged_file_before_storage(monkeypatch):
    space = make_space("service-file-owner-initial")
    row, machine = service_request(space)
    actor, owner = manager(space), manager(space)
    file = ServiceRequestFile.objects.create(
        machine=machine,
        kind="attachment",
        object_key="machine/other-owner",
        content_type="application/pdf",
        original_filename="private.pdf",
        owner_user_id=owner.pk,
    )
    promote, cleanup = Mock(return_value=4), Mock()
    monkeypatch.setattr(service_storage, "finalize_upload", promote)
    monkeypatch.setattr(service_storage, "cleanup_upload", cleanup)

    with pytest.raises(ValidationError):
        service_storage.finalize_file(row, file_id=file.pk, actor=actor)

    promote.assert_not_called()
    cleanup.assert_not_called()
    assert ServiceRequestFile.objects.get(pk=file.pk).service_request_id is None


def test_finalize_rechecks_staged_file_owner_under_lock(monkeypatch):
    space = make_space("service-file-owner-locked")
    row, machine = service_request(space)
    actor, new_owner = manager(space), manager(space)
    file = ServiceRequestFile.objects.create(
        machine=machine,
        kind="attachment",
        object_key="machine/owner-race",
        content_type="application/pdf",
        original_filename="private.pdf",
        owner_user_id=actor.pk,
    )

    def change_owner_during_promotion(*args):
        ServiceRequestFile.objects.filter(pk=file.pk).update(owner_user_id=new_owner.pk)
        return 4

    cleanup = Mock()
    monkeypatch.setattr(service_storage, "finalize_upload", change_owner_during_promotion)
    monkeypatch.setattr(service_storage, "validate_service_object", lambda *args: fake_result())
    monkeypatch.setattr(service_storage, "cleanup_upload", cleanup)

    with pytest.raises(ValidationError):
        service_storage.finalize_file(row, file_id=file.pk, actor=actor)

    file.refresh_from_db()
    assert file.owner_user_id == new_owner.pk
    assert file.service_request_id is None
    cleanup.assert_called_once_with(file.object_key)


def test_policy_snapshot_ignores_later_machine_policy_edit(monkeypatch):
    space = make_space("service-file-policy")
    row, machine = service_request(space)
    actor = manager(space)
    file = ServiceRequestFile.objects.create(
        machine=machine, kind="attachment", object_key="machine/key", content_type="application/pdf",
        original_filename="report.pdf", owner_user_id=actor.pk, file_policy_name="documents", file_policy_version=1,
    )
    Machine.objects.filter(pk=machine.pk).update(service_file_policy={"name": "removed", "version": 99})
    monkeypatch.setattr(service_storage, "finalize_upload", lambda *args: 4)
    monkeypatch.setattr(service_storage, "validate_service_object", lambda *args: fake_result())

    service_storage.finalize_file(row, file_id=file.pk, actor=actor)
    file.refresh_from_db()
    assert (file.file_policy_name, file.file_policy_version, file.service_request_id) == ("documents", 1, row.pk)


def test_signed_url_manager_only_attached_only_and_cross_tenant(monkeypatch):
    space, other = make_space("service-file-url"), make_space("service-file-url-other")
    row, machine = service_request(space)
    staged = ServiceRequestFile.objects.create(machine=machine, kind="attachment", object_key="machine/staged", owner_user_id=1)
    attached = ServiceRequestFile.objects.create(
        machine=machine, service_request=row, kind="attachment", object_key="machine/attached", owner_user_id=1,
        size_bytes=4, attached_at=row.created_at,
    )
    monkeypatch.setattr(service_storage, "presigned_get_url", lambda *args: "https://download.test")

    assert authenticated_client(manager(space)).get(reverse("admin-machine-service-file-url", kwargs={"pk": attached.pk})).status_code == 200
    assert authenticated_client(manager(space)).get(reverse("admin-machine-service-file-url", kwargs={"pk": staged.pk})).status_code == 404
    assert authenticated_client(manager(other)).get(reverse("admin-machine-service-file-url", kwargs={"pk": attached.pk})).status_code == 404


def test_delete_staged_file_frees_storage(monkeypatch):
    space = make_space("service-file-delete")
    _, machine = service_request(space)
    file = ServiceRequestFile.objects.create(machine=machine, kind="attachment", object_key="machine/staged", owner_user_id=1, size_bytes=33)
    free_storage, cleanup = Mock(), Mock()
    monkeypatch.setattr("apps.machines.service_storage.limits.free_storage", free_storage)
    monkeypatch.setattr(service_storage, "cleanup_upload", cleanup)

    service_storage.delete_staged_file(file, actor=manager(space))
    free_storage.assert_called_once_with(space, 33)
    cleanup.assert_called_once_with("machine/staged")
    assert not ServiceRequestFile.objects.filter(pk=file.pk).exists()


def test_machine_file_policy_rejects_unknown_name():
    space = make_space("service-file-policy-validation")
    _, machine = service_request(space)
    machine.service_file_policy = {"name": "anything", "version": 1}
    with pytest.raises(DjangoValidationError):
        machine.full_clean()
