import pytest
from django.contrib.auth import get_user_model
from django.db import Error, transaction
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.evidence.models import EvidencePhoto
from apps.evidence.storage import StorageUnavailable
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def make_user(username, role=User.Role.REQUESTER, **kw):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@e.com", role=role, **kw
    )


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_superadmin(username):
    return make_user(
        username,
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )


def make_member(username, makerspace, membership_role="space_manager", role=User.Role.SPACE_MANAGER):
    user = make_user(username, role=role, access_status=User.AccessStatus.ACTIVE)
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=membership_role,
    )
    return user


def upload_url(makerspace):
    return reverse(
        "evidence_admin:evidence-upload-url",
        kwargs={"makerspace_id": makerspace.id},
    )


def upload_url_for_id(makerspace_id):
    return reverse(
        "evidence_admin:evidence-upload-url",
        kwargs={"makerspace_id": makerspace_id},
    )


def detail_url(photo):
    return reverse("evidence_admin:evidence-detail", kwargs={"pk": photo.id})


def make_photo(makerspace, uploaded_by, object_key="evidence/original.png"):
    return EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=object_key,
        uploaded_by=uploaded_by,
    )


def mock_upload(monkeypatch):
    monkeypatch.setattr(
        "apps.evidence.views.presigned_upload",
        lambda object_key, content_type: {
            "url": "http://minio/evidence",
            "fields": {"key": "k", "Content-Type": "image/png"},
        },
    )


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_evidence_photo_model_guard_blocks_save_and_delete():
    makerspace = make_space("evidence-guard")
    uploader = make_user("evidence-uploader", role=User.Role.SPACE_MANAGER)
    photo = make_photo(makerspace, uploader)

    with pytest.raises(RuntimeError):
        photo.save()

    with pytest.raises(RuntimeError):
        photo.delete()


def test_evidence_photo_database_trigger_blocks_update_and_delete():
    makerspace = make_space("evidence-trigger")
    uploader = make_user("evidence-trigger-uploader", role=User.Role.SPACE_MANAGER)
    photo = make_photo(makerspace, uploader)

    with pytest.raises(Error):
        with transaction.atomic():
            EvidencePhoto.objects.filter(pk=photo.pk).update(object_key="y")

    with pytest.raises(Error):
        with transaction.atomic():
            EvidencePhoto.objects.filter(pk=photo.pk).delete()


def test_admin_member_can_request_upload_url(monkeypatch):
    mock_upload(monkeypatch)
    makerspace = make_space("upload-admin")
    user = make_member("upload-admin-user", makerspace)

    response = authenticated_client(user).post(
        upload_url(makerspace),
        {"evidence_type": "issue", "content_type": "image/png", "size_bytes": 12345},
        format="json",
    )

    assert response.status_code == 201
    assert set(response.data) == {"evidence_id", "upload_url", "fields", "object_key"}
    assert response.data["upload_url"] == "http://minio/evidence"
    assert response.data["fields"] == {"key": "k", "Content-Type": "image/png"}
    photo = EvidencePhoto.objects.get()
    assert photo.makerspace == makerspace
    assert photo.object_key == response.data["object_key"]
    assert photo.content_type == "image/png"
    assert photo.size_bytes == 12345
    assert response.data["evidence_id"] == photo.id
    audit = AuditLog.objects.get()
    assert audit.action == "evidence.upload_url_issued"
    assert audit.makerspace == makerspace


def test_admin_member_can_request_put_upload_url(monkeypatch, settings):
    settings.STORAGE_PRESIGN_METHOD = "put"
    makerspace = make_space("upload-put-admin")
    user = make_member("upload-put-admin-user", makerspace)

    class FakePublicClient:
        def generate_presigned_url(self, operation, Params, ExpiresIn):
            assert operation == "put_object"
            assert Params["Bucket"] == settings.AWS_STORAGE_BUCKET_NAME
            assert Params["ContentType"] == "image/png"
            assert ExpiresIn == settings.EVIDENCE_URL_TTL_SECONDS
            return "http://minio/evidence-put"

    monkeypatch.setattr(
        "apps.evidence.storage._public_client",
        lambda: FakePublicClient(),
    )

    response = authenticated_client(user).post(
        upload_url(makerspace),
        {"evidence_type": "issue", "content_type": "image/png", "size_bytes": 12345},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["method"] == "PUT"
    assert response.data["headers"] == {"Content-Type": "image/png"}
    assert isinstance(response.data["upload_url"], str)


def test_guest_admin_member_can_request_upload_url(monkeypatch):
    mock_upload(monkeypatch)
    makerspace = make_space("upload-guest")
    user = make_handout_member("upload-guest-user", makerspace)

    response = authenticated_client(user).post(
        upload_url(makerspace),
        {"evidence_type": "issue", "content_type": "image/png", "size_bytes": 12345},
        format="json",
    )

    assert response.status_code == 201
    assert EvidencePhoto.objects.count() == 1
    assert AuditLog.objects.filter(action="evidence.upload_url_issued").count() == 1


def test_existing_requester_promoted_to_inventory_manager_can_request_upload_url(monkeypatch):
    mock_upload(monkeypatch)
    makerspace = make_space("upload-inventory-promoted")
    user = make_user(
        "upload-inventory-promoted-user",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )

    response = authenticated_client(user).post(
        upload_url(makerspace),
        {"evidence_type": "issue", "content_type": "image/png", "size_bytes": 12345},
        format="json",
    )

    assert response.status_code == 201
    user.refresh_from_db()
    assert user.role == User.Role.REQUESTER
    assert EvidencePhoto.objects.count() == 1


def test_suspended_inventory_manager_cannot_request_upload_url(monkeypatch):
    mock_upload(monkeypatch)
    makerspace = make_space("upload-inventory-suspended")
    user = make_member(
        "upload-inventory-suspended-user",
        makerspace,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )
    user.access_status = User.AccessStatus.SUSPENDED
    user.save(update_fields=["access_status"])

    response = authenticated_client(user).post(
        upload_url(makerspace),
        {"evidence_type": "issue", "content_type": "image/png", "size_bytes": 12345},
        format="json",
    )

    assert response.status_code == 403
    assert EvidencePhoto.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_requester_cannot_request_upload_url(monkeypatch):
    mock_upload(monkeypatch)
    makerspace = make_space("upload-denied")

    response = authenticated_client(make_user("upload-requester")).post(
        upload_url(makerspace),
        {"evidence_type": "issue", "content_type": "image/png", "size_bytes": 12345},
        format="json",
    )

    assert response.status_code == 403
    assert EvidencePhoto.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_unauthenticated_client_cannot_request_upload_url(monkeypatch):
    mock_upload(monkeypatch)
    makerspace = make_space("upload-unauthenticated")

    response = APIClient().post(
        upload_url(makerspace),
        {"evidence_type": "issue", "content_type": "image/png", "size_bytes": 12345},
        format="json",
    )

    assert response.status_code == 401
    assert EvidencePhoto.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_staff_user_without_membership_cannot_request_upload_url(monkeypatch):
    mock_upload(monkeypatch)
    makerspace = make_space("upload-cross-tenant")
    user = make_user(
        "upload-cross-tenant-admin",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
    )

    response = authenticated_client(user).post(
        upload_url(makerspace),
        {"evidence_type": "issue", "content_type": "image/png", "size_bytes": 12345},
        format="json",
    )

    assert response.status_code == 403
    assert EvidencePhoto.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_upload_url_with_missing_makerspace_returns_404(monkeypatch):
    monkeypatch.setattr(
        "apps.evidence.views.presigned_upload",
        lambda object_key, content_type: pytest.fail("storage should not be called"),
    )
    missing_id = Makerspace.objects.order_by("-id").first()
    missing_id = (missing_id.id if missing_id else 0) + 1000
    user = make_superadmin("upload-missing-space-super")

    response = authenticated_client(user).post(
        upload_url_for_id(missing_id),
        {"evidence_type": "issue", "content_type": "image/png", "size_bytes": 12345},
        format="json",
    )

    assert response.status_code == 404
    assert EvidencePhoto.objects.count() == 0
    assert AuditLog.objects.count() == 0


@pytest.mark.parametrize("content_type", ["image/svg+xml", "application/pdf"])
def test_bad_upload_content_type_returns_400_without_creating_rows(
    monkeypatch,
    content_type,
):
    mock_upload(monkeypatch)
    makerspace = make_space(f"upload-bad-{content_type.split('/')[1].replace('+', '-')}")
    user = make_member(f"upload-bad-{content_type.split('/')[1]}", makerspace)

    response = authenticated_client(user).post(
        upload_url(makerspace),
        {"evidence_type": "issue", "content_type": content_type},
        format="json",
    )

    assert response.status_code == 400
    assert EvidencePhoto.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_upload_storage_unavailable_returns_503_without_creating_rows(monkeypatch):
    makerspace = make_space("upload-storage-down")
    user = make_member("upload-storage-down-user", makerspace)
    monkeypatch.setattr(
        "apps.evidence.views.presigned_upload",
        lambda object_key, content_type: (_ for _ in ()).throw(StorageUnavailable()),
    )
    evidence_count = EvidencePhoto.objects.count()
    audit_count = AuditLog.objects.count()

    response = authenticated_client(user).post(
        upload_url(makerspace),
        {"evidence_type": "issue", "content_type": "image/png", "size_bytes": 12345},
        format="json",
    )

    assert response.status_code == 503
    assert EvidencePhoto.objects.count() == evidence_count
    assert AuditLog.objects.count() == audit_count


def test_admin_member_can_get_evidence_detail_url_and_audit_is_written(monkeypatch):
    makerspace = make_space("detail-admin")
    user = make_member("detail-admin-user", makerspace)
    photo = make_photo(makerspace, user)
    monkeypatch.setattr("apps.evidence.views.object_exists", lambda object_key: True)
    monkeypatch.setattr(
        "apps.evidence.views.presigned_get_url",
        lambda object_key: "http://minio/get",
    )

    response = authenticated_client(user).get(detail_url(photo))

    assert response.status_code == 200
    assert response.data == {"url": "http://minio/get", "expires_in": 300}
    audit = AuditLog.objects.get()
    assert audit.action == "evidence.viewed"
    assert audit.makerspace == makerspace


def test_evidence_detail_is_scoped_to_user_makerspaces(monkeypatch):
    own_space = make_space("detail-own-space")
    other_space = make_space("detail-other-space")
    user = make_member("detail-scoped-admin", own_space)
    other_admin = make_user("detail-other-admin", role=User.Role.SPACE_MANAGER)
    photo = make_photo(other_space, other_admin, object_key="evidence/other.png")
    monkeypatch.setattr("apps.evidence.views.object_exists", lambda object_key: True)
    monkeypatch.setattr(
        "apps.evidence.views.presigned_get_url",
        lambda object_key: "http://minio/get",
    )

    response = authenticated_client(user).get(detail_url(photo))

    assert response.status_code == 404
    assert AuditLog.objects.count() == 0


def test_superadmin_cannot_get_hidden_makerspace_evidence_detail(monkeypatch):
    makerspace = make_space("detail-hidden-space")
    makerspace.superadmin_access_enabled = False
    makerspace.save(update_fields=["superadmin_access_enabled"])
    uploader = make_member("detail-hidden-uploader", makerspace)
    photo = make_photo(makerspace, uploader)
    superadmin = make_superadmin("detail-hidden-super")
    monkeypatch.setattr(
        "apps.evidence.views.object_exists",
        lambda object_key: pytest.fail("storage should not be checked"),
    )
    monkeypatch.setattr(
        "apps.evidence.views.presigned_get_url",
        lambda object_key: pytest.fail("signed URL should not be issued"),
    )

    response = authenticated_client(superadmin).get(detail_url(photo))

    assert response.status_code == 404
    assert AuditLog.objects.count() == 0


def test_evidence_detail_requires_upload_evidence_action_in_makerspace(monkeypatch):
    makerspace = make_space("detail-no-upload-action")
    uploader = make_member("detail-no-upload-owner", makerspace)
    viewer = make_member(
        "detail-no-upload-viewer",
        makerspace,
        membership_role=MakerspaceMembership.Role.PRINT_MANAGER,
        role=User.Role.REQUESTER,
    )
    photo = make_photo(makerspace, uploader)
    monkeypatch.setattr("apps.evidence.views.object_exists", lambda object_key: True)
    monkeypatch.setattr(
        "apps.evidence.views.presigned_get_url",
        lambda object_key: "http://minio/get",
    )

    response = authenticated_client(viewer).get(detail_url(photo))

    assert response.status_code == 404
    assert AuditLog.objects.count() == 0


def test_evidence_detail_returns_409_when_object_is_missing(monkeypatch):
    makerspace = make_space("detail-missing-object")
    user = make_member("detail-missing-user", makerspace)
    photo = make_photo(makerspace, user)
    monkeypatch.setattr("apps.evidence.views.object_exists", lambda object_key: False)
    monkeypatch.setattr(
        "apps.evidence.views.presigned_get_url",
        lambda object_key: "http://minio/get",
    )

    response = authenticated_client(user).get(detail_url(photo))

    assert response.status_code == 409
    assert AuditLog.objects.count() == 0


def test_evidence_detail_returns_503_when_object_exists_check_fails(monkeypatch):
    makerspace = make_space("detail-head-storage-down")
    user = make_member("detail-head-storage-user", makerspace)
    photo = make_photo(makerspace, user)
    monkeypatch.setattr(
        "apps.evidence.views.object_exists",
        lambda object_key: (_ for _ in ()).throw(StorageUnavailable()),
    )
    monkeypatch.setattr(
        "apps.evidence.views.presigned_get_url",
        lambda object_key: "http://minio/get",
    )

    response = authenticated_client(user).get(detail_url(photo))

    assert response.status_code == 503
    assert AuditLog.objects.count() == 0


def test_evidence_detail_returns_503_when_get_url_fails(monkeypatch):
    makerspace = make_space("detail-get-storage-down")
    user = make_member("detail-get-storage-user", makerspace)
    photo = make_photo(makerspace, user)
    monkeypatch.setattr("apps.evidence.views.object_exists", lambda object_key: True)
    monkeypatch.setattr(
        "apps.evidence.views.presigned_get_url",
        lambda object_key: (_ for _ in ()).throw(StorageUnavailable()),
    )

    response = authenticated_client(user).get(detail_url(photo))

    assert response.status_code == 503
    assert AuditLog.objects.count() == 0
