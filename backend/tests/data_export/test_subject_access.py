"""Subject exports prove row ownership independently of staff authority."""

import json
import zipfile
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.data_export import services, storage
from apps.data_export.models import DataExportJob
from apps.data_export.subject_archive import build_subject_archive
from apps.data_export.subject_services import create_subject_export, run_subject_export
from apps.hardware_requests.models import HardwareRequest
from apps.machines.models import MachineServiceRequest, MachineType, ServiceQueue
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MemberProfile
from apps.payments.models import Payment
from tests.encryption.conftest import enabled_encryption

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def subject_setup():
    cache.clear()
    member = User.objects.create_user(username="subject-owner", email="owner@example.test")
    other = User.objects.create_user(username="SUBJECT-OTHER-USER", email="OTHER@example.test")
    local = Makerspace.objects.create(
        name="Subject tenant", slug="subject-tenant",
        enabled_modules=["membership", "member_accounts"], enabled_features=["membership.self_export"],
    )
    foreign = Makerspace.objects.create(name="FOREIGN-TENANT", slug="subject-foreign",
                                       enabled_modules=["membership", "member_accounts"],
                                       enabled_features=["membership.self_export"])
    own = MakerspaceMembership.objects.create(makerspace=local, user=member, role="member")
    somebody = MakerspaceMembership.objects.create(makerspace=local, user=other, role="member")
    outside = MakerspaceMembership.objects.create(makerspace=foreign, user=member, role="member")
    MemberProfile.objects.create(membership=own, bio="OWNER-PROFILE")
    MemberProfile.objects.create(membership=somebody, bio="OTHER-PROFILE-SECRET")
    MemberProfile.objects.create(membership=outside, bio="FOREIGN-PROFILE-SECRET")
    yield member, other, local, foreign, own
    cache.clear()


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def url(name, makerspace, job=None):
    kwargs = {"makerspace_id": makerspace.pk}
    if job:
        kwargs["job_id"] = job.pk
    return reverse(name, kwargs=kwargs)


def files_for(job):
    DataExportJob.objects.filter(pk=job.pk).update(deadline_at=timezone.now() + timedelta(minutes=5))
    job.refresh_from_db()
    path, manifest, tempdir = build_subject_archive(job)
    try:
        with zipfile.ZipFile(path) as archive:
            files = {name: json.loads(archive.read(name)) for name in archive.namelist()}
        return files, manifest
    finally:
        tempdir.cleanup()


def test_archive_contains_only_own_tenant_rows_and_no_other_identity(subject_setup):
    member, other, local, foreign, membership = subject_setup
    for user, tenant, label in (
        (member, local, "OWN-LOAN"), (other, local, "OTHER-LOAN-SECRET"),
        (member, foreign, "FOREIGN-LOAN-SECRET"),
    ):
        HardwareRequest.objects.create(
            makerspace=tenant, requester=user, requester_username=user.username,
            requester_name=label, requester_contact_email=user.email,
        )
        membership_row = MakerspaceMembership.objects.get(user=user, makerspace=tenant)
        Payment.objects.create(makerspace=tenant, member=user, created_by=member,
                               subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
                               subject_id=membership_row.pk, subject_label=label,
                               amount="12", currency="usd", provider="unclaimed")
    audit.record(member, "subject.fixture", makerspace=local,
                 target=other, meta={"private": "OTHER-AUDIT-SECRET"})
    files, manifest = files_for(create_subject_export(member, local))
    flattened = json.dumps(files)
    assert "OWN-LOAN" in flattened and "OWNER-PROFILE" in flattened
    for sentinel in ("OTHER-PROFILE-SECRET", "FOREIGN-PROFILE-SECRET", "OTHER-LOAN-SECRET",
                     "FOREIGN-LOAN-SECRET", "SUBJECT-OTHER-USER", "OTHER@example.test", "OTHER-AUDIT-SECRET"):
        assert sentinel not in flattened
    assert len(files["global/users.json"]) == 1
    person = files["global/users.json"][0]
    assert person["id"] == member.pk and person["email"] == member.email
    assert set(person) == {"id", "username", "email", "first_name", "last_name",
                           "display_name", "phone", "date_joined"}
    assert manifest["row_counts"]["payments.Payment"] == 1
    assert manifest["row_counts"]["makerspaces.MemberProfile"] == 1
    assert all("password" not in row for row in files["global/users.json"])


def test_staff_authoring_other_persons_request_is_not_subject_ownership(subject_setup):
    member, other, local, _foreign, _membership = subject_setup
    HardwareRequest.objects.create(makerspace=local, requester=other,
                                   requester_username=other.username, accepted_by=member,
                                   requester_name="ANOTHER-PERSON")
    # Legacy service requester is the staff creator; only the member FK establishes
    # ownership. A nullable historical member never proves the creator was the subject.
    machine_type = MachineType.objects.create(makerspace=local, slug="subject-type", name="Subject type")
    queue = ServiceQueue.objects.create(makerspace=local, machine_type=machine_type, name="Subject queue")
    MachineServiceRequest.objects.create(makerspace=local, requester=member, queue=queue,
                                        requester_name="ANOTHER-SERVICE-BORROWER", title="Legacy service")
    files, _ = files_for(create_subject_export(member, local))
    assert files["lending/requests.json"] == []
    assert "ANOTHER-SERVICE-BORROWER" not in json.dumps(files)


def test_shared_claim_preserves_the_workers_tenant_scope(subject_setup):
    member, _other, local, foreign, _membership = subject_setup
    own = create_subject_export(member, local)
    outside = create_subject_export(member, foreign)
    jobs = rbac.scope_for_scheduled_work(DataExportJob.objects.all(), makerspace_id=local.pk)
    assert services._claim_job(outside.pk, queryset=jobs) is None
    outside.refresh_from_db()
    assert outside.status == DataExportJob.Status.PENDING and outside.started_at is None
    assert not AuditLog.objects.filter(action="subject_export.started", target_id=str(outside.pk)).exists()
    claimed = services._claim_job(own.pk, queryset=jobs)
    assert claimed.status == DataExportJob.Status.RUNNING
    assert AuditLog.objects.filter(action="subject_export.started", target_id=str(own.pk)).count() == 1


def test_export_request_queue_poll_download_and_audits(subject_setup, monkeypatch):
    member, _other, local, _foreign, _membership = subject_setup
    queued = []
    monkeypatch.setattr("apps.data_export.subject_views.run_subject_export_task.delay", queued.append)
    response = client_for(member).post(url("member-subject-export-list", local), {}, format="json")
    assert response.status_code == 202
    job = DataExportJob.objects.get(pk=response.data["id"])
    assert queued == [str(job.pk)]
    monkeypatch.setattr(storage, "upload_archive", lambda *args: None)
    monkeypatch.setattr(storage, "delete_object", lambda *args: True)
    run_subject_export(job.pk)
    job.refresh_from_db()
    assert job.status == "available" and job.accounted_size_bytes > 0
    client = client_for(member)
    assert client.get(url("member-subject-export-detail", local, job)).status_code == 200
    signed = []
    monkeypatch.setattr(storage, "signed_archive_url", lambda key, ttl: signed.append((key, ttl)) or "https://files.example.test/personal.zip?signature=PRIVATE-SIGNATURE")
    download = client.post(url("member-subject-export-download", local, job))
    assert download.status_code == 200 and signed[0][1] <= 600
    assert download["Cache-Control"] == "private, no-store"
    actions = set(AuditLog.objects.filter(makerspace=local, actor=member).values_list("action", flat=True))
    assert {"subject_export.requested", "subject_export.started", "data_export.completed",
            "subject_export.download_url_issued"} <= actions
    assert "PRIVATE-SIGNATURE" not in json.dumps(list(AuditLog.objects.filter(makerspace=local).values_list("meta", flat=True)))


def test_other_member_other_tenant_and_staff_cannot_download_subject_job(subject_setup, monkeypatch):
    member, other, local, foreign, _membership = subject_setup
    job = create_subject_export(member, local)
    for name in ("member-subject-export-detail", "member-subject-export-download"):
        method = "get" if name.endswith("detail") else "post"
        assert getattr(client_for(other), method)(url(name, local, job)).status_code == 404
        assert getattr(client_for(member), method)(url(name, foreign, job)).status_code == 404
    manager = User.objects.create_user(username="subject-staff")
    MakerspaceMembership.objects.create(user=manager, makerspace=local, role="space_manager")
    assert client_for(manager).get(reverse("data-export-detail", kwargs={"makerspace_id": local.pk, "job_id": job.pk})).status_code == 404
    assert services.run_export_job(job.pk) is None
    job.refresh_from_db()
    assert job.status == "pending"


def test_throttle_survives_cache_reset_and_request_cannot_choose_subject(subject_setup, monkeypatch):
    member, other, local, _foreign, _membership = subject_setup
    monkeypatch.setattr("apps.data_export.subject_views.run_subject_export_task.delay", lambda *_: None)
    client = client_for(member)
    endpoint = url("member-subject-export-list", local)
    assert client.post(endpoint, {"user_id": other.pk}, format="json").status_code == 400
    cache.clear()
    assert client.post(endpoint, {}, format="json").status_code == 202
    assert client.post(endpoint, {}, format="json").status_code == 429
    cache.clear()
    assert client.post(endpoint, {}, format="json").status_code == 429
    assert DataExportJob.objects.filter(requested_by=member).count() == 1


def test_module_and_feature_off_return_400_and_create_nothing(subject_setup):
    member, _other, local, _foreign, _membership = subject_setup
    client = client_for(member)
    endpoint = url("member-subject-export-list", local)
    for modules, features in ((["member_accounts"], ["membership.self_export"]),
                              (["membership"], ["membership.self_export"]),
                              (["membership", "member_accounts"], [])):
        cache.clear()
        Makerspace.objects.filter(pk=local.pk).update(enabled_modules=modules, enabled_features=features)
        assert client.post(endpoint, {}, format="json").status_code == 400
    assert not DataExportJob.objects.exists()


@pytest.mark.parametrize("disabled", ["membership", "member_accounts", "feature"])
def test_disabled_export_returns_400_even_with_a_full_daily_throttle(subject_setup, monkeypatch, disabled):
    member, _other, local, _foreign, _membership = subject_setup
    monkeypatch.setattr("apps.data_export.subject_views.run_subject_export_task.delay", lambda *_: None)
    client = client_for(member)
    endpoint = url("member-subject-export-list", local)
    assert client.post(endpoint, {}, format="json").status_code == 202
    if disabled == "feature":
        Makerspace.objects.filter(pk=local.pk).update(enabled_features=[])
    else:
        Makerspace.objects.filter(pk=local.pk).update(enabled_modules=[
            item for item in local.enabled_modules if item != disabled
        ])
    assert client.post(endpoint, {}, format="json").status_code == 400
    assert DataExportJob.objects.filter(requested_by=member).count() == 1


def test_leaving_while_job_is_queued_fails_without_storage_disclosure(subject_setup, monkeypatch):
    member, _other, local, _foreign, membership = subject_setup
    job = create_subject_export(member, local)
    MakerspaceMembership.objects.filter(pk=membership.pk).update(status="revoked")
    calls = []
    monkeypatch.setattr(storage, "upload_archive", lambda *args: calls.append(args))
    monkeypatch.setattr(storage, "delete_object", lambda *args: True)
    run_subject_export(job.pk)
    job.refresh_from_db()
    assert job.status == "failed" and not calls


def test_expired_job_cannot_get_signed_download(subject_setup, monkeypatch):
    member, _other, local, _foreign, _membership = subject_setup
    job = create_subject_export(member, local)
    DataExportJob.objects.filter(pk=job.pk).update(status="available", expires_at=timezone.now() - timedelta(seconds=1))
    monkeypatch.setattr(storage, "signed_archive_url", lambda *_: pytest.fail("Expired archive was signed"))
    response = client_for(member).post(url("member-subject-export-download", local, job))
    assert response.status_code == 400


def test_subject_export_decrypts_owners_scoped_pii(subject_setup):
    member, _other, local, _foreign, _membership = subject_setup
    with enabled_encryption():
        row = HardwareRequest.objects.create(
            makerspace=local, requester=member, requester_username=member.username,
            requester_name="PRIVATE-PLAINTEXT-OWNER", requester_contact_email="private@example.test",
        )
        files, _ = files_for(create_subject_export(member, local))
    emitted = files["lending/requests.json"]
    assert len(emitted) == 1 and emitted[0]["id"] == row.pk
    assert emitted[0]["requester_name"] == "PRIVATE-PLAINTEXT-OWNER"
    assert emitted[0]["requester_contact_email"] == "private@example.test"


def test_pending_export_is_recovered_when_broker_enqueue_fails(subject_setup, monkeypatch):
    from apps.data_export.subject_tasks import sweep_subject_exports_task

    member, _other, local, _foreign, _membership = subject_setup
    def unavailable(*_args):
        raise OSError("Broker unavailable")
    monkeypatch.setattr("apps.data_export.subject_views.run_subject_export_task.delay", unavailable)
    monkeypatch.setattr(storage, "upload_archive", lambda *args: None)
    monkeypatch.setattr(storage, "delete_object", lambda *args: True)
    response = client_for(member).post(url("member-subject-export-list", local), {}, format="json")
    assert response.status_code == 202
    job = DataExportJob.objects.get(pk=response.data["id"])
    assert job.status == "pending"
    outcome = sweep_subject_exports_task.run()
    job.refresh_from_db()
    assert outcome["processed"] == 1 and job.status == "available"


def test_storage_quota_failure_is_typed_and_never_publishes_an_archive(subject_setup, monkeypatch):
    from rest_framework.exceptions import ValidationError

    member, _other, local, _foreign, _membership = subject_setup
    job = create_subject_export(member, local)
    def storage_full(*_args):
        raise ValidationError({"limit": "Storage cap reached."})
    deleted = []
    monkeypatch.setattr(storage, "upload_archive", lambda *_: None)
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key) or True)
    monkeypatch.setattr("apps.makerspaces.limits.add_storage", storage_full)
    run_subject_export(job.pk)
    job.refresh_from_db()
    assert job.status == "failed" and job.failure_code == "quota_exceeded"
    assert job.accounted_size_bytes == 0 and job.object_key in deleted
    assert not AuditLog.objects.filter(action="data_export.completed", target_id=str(job.pk)).exists()
