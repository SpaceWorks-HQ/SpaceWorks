import json
import uuid
import zipfile

import pytest

from apps.accounts.models import User
from apps.data_export.runner import build_archive
from apps.makerspaces.models import MakerspaceMembership, MembershipRequest
from apps.tenant_migration import admission
from apps.tenant_migration.models import MigrationPairing, TenantMigrationExportJob
from apps.tenant_migration.protocol_errors import ClosureAdmissionError
from tests.data_export.portable_helpers import make_job, make_space, make_user

pytestmark = pytest.mark.django_db(transaction=True)


def superuser(username):
    return User.objects.create_superuser(
        username=username,
        email=f"{username}@example.test",
        password="test-password",
        access_status=User.AccessStatus.ACTIVE,
    )


def approve_current(actor, space, *, denied=()):
    closure = admission.compute_pending_closure(space)
    denied = {str(value) for value in denied}
    decisions = [
        {"user_id": item["id"], "approved": str(item["id"]) not in denied}
        for item in closure["identities"]
    ]
    return admission.approve_closure(
        actor=actor, makerspace=space, digest=closure["digest"], decisions=decisions
    )


def migration_job(space, actor, approval):
    job = make_job(space, actor, attach_approval=False)
    TenantMigrationExportJob.objects.create(
        export_job=job,
        disclosure_approval=approval,
        closure_digest=approval.closure_digest,
        target_age_recipient="age1targetrecipient000000000000",
    )
    return job


def test_planted_invitation_cannot_disclose_unrelated_portable_pii_in_archive_bytes():
    actor = superuser("source-root-invitation")
    space = make_space("admission-invitation")
    unrelated = make_user("INVITATION-PII-SENTINEL")
    unrelated.email = "invitation-private@example.test"
    unrelated.first_name = "InvitationPrivateName"
    unrelated.save(update_fields=("email", "first_name"))
    MembershipRequest.objects.create(
        makerspace=space,
        user=unrelated,
        invite_email=unrelated.email,
        kind=MembershipRequest.Kind.INVITE,
        state=MembershipRequest.State.INVITED,
    )
    approval = approve_current(actor, space)
    job = migration_job(space, actor, approval)

    path, _manifest, tempdir = build_archive(job, page_size=2)
    try:
        with zipfile.ZipFile(path) as archive:
            archive_bytes = b"\n".join(
                archive.read(name) for name in archive.namelist()
            )
    finally:
        tempdir.cleanup()

    assert unrelated.email.encode() not in archive_bytes
    assert unrelated.first_name.encode() not in archive_bytes
    assert unrelated.username.encode() not in archive_bytes


def test_planted_active_member_cannot_disclose_under_blanket_migration_approval(
    monkeypatch,
):
    actor = superuser("source-root-membership")
    space = make_space("admission-membership")
    unrelated = make_user("MEMBERSHIP-PII-SENTINEL")
    unrelated.email = "membership-private@example.test"
    unrelated.first_name = "MembershipPrivateName"
    unrelated.save(update_fields=("email", "first_name"))
    MakerspaceMembership.objects.create(
        makerspace=space,
        user=unrelated,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=space.roles.get(slug="member"),
        status="active",
    )
    approval = approve_current(actor, space, denied=(unrelated.pk,))
    MigrationPairing.objects.create(
        migration_id=uuid.uuid4(), source_tenant_id=str(space.pk),
        archive_digest="b" * 64, source_deployment_id="source",
        source_public_key="s" * 44, source_fingerprint="1" * 64,
        target_deployment_id="target", target_public_key="t" * 44,
        target_fingerprint="2" * 64, approved_by=actor,
    )
    job = migration_job(space, actor, approval)
    packaged = []
    monkeypatch.setattr(
        "apps.data_export.runner.shutil.make_archive",
        lambda *_args, **_kwargs: packaged.append(True),
    )

    with pytest.raises(
        ClosureAdmissionError,
        match="makerspaces.MakerspaceMembership.user",
    ):
        build_archive(job, page_size=2)

    assert packaged == []


def test_closure_change_after_approval_voids_export():
    actor = superuser("source-root-digest")
    space = make_space("admission-digest")
    first = make_user("digest-first")
    MakerspaceMembership.objects.create(
        makerspace=space, user=first, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=space.roles.get(slug="member"), status="active",
    )
    approval = approve_current(actor, space)
    second = make_user("digest-second")
    MakerspaceMembership.objects.create(
        makerspace=space, user=second, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=space.roles.get(slug="member"), status="active",
    )
    job = migration_job(space, actor, approval)

    with pytest.raises(ClosureAdmissionError, match="changed after approval"):
        build_archive(job, page_size=2)


def test_denied_nullable_identity_becomes_an_opaque_inert_reference():
    actor = superuser("source-root-nullable")
    space = make_space("admission-nullable")
    unrelated = make_user("NULLABLE-PII-SENTINEL")
    unrelated.email = "nullable-private@example.test"
    unrelated.save(update_fields=("email",))
    space.created_by = unrelated
    space.save(update_fields=("created_by",))
    approval = approve_current(actor, space, denied=(unrelated.pk,))
    job = migration_job(space, actor, approval)

    path, _manifest, tempdir = build_archive(job, page_size=2)
    try:
        with zipfile.ZipFile(path) as archive:
            archive_bytes = b"\n".join(
                archive.read(name) for name in archive.namelist()
            )
            references = [
                json.loads(line)
                for line in archive.read(
                    "migration/external_references.jsonl"
                ).decode().splitlines()
            ]
    finally:
        tempdir.cleanup()

    assert unrelated.email.encode() not in archive_bytes
    assert {
        "source_model_label": "makerspaces.Makerspace",
        "source_object_id": str(space.pk),
        "field_name": "created_by",
        "target_model_label": "accounts.User",
        "target_object_id": str(unrelated.pk),
        "snapshot": {"kind": "withheld_identity"},
    } in references


def test_portable_runner_refuses_a_blanket_job_without_identity_approval():
    actor = superuser("source-root-no-approval")
    space = make_space("admission-required")
    job = make_job(space, actor, attach_approval=False)

    with pytest.raises(ClosureAdmissionError, match="exact source-superadmin"):
        build_archive(job, page_size=2)


def test_target_seeded_rows_remain_in_archive_but_are_closure_inert():
    space = make_space("admission-seeded-row")
    member_role = space.roles.get(slug="member")

    assert admission.export_row_policy(
        "makerspaces.MakerspaceRole", member_role
    ) == (True, False)
