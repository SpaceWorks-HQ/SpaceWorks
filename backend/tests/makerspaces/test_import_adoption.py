from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts import services_registration
from apps.accounts.models import EmailVerificationChallenge, User
from apps.audit.models import AuditLog
from apps.makerspaces.import_adoption import (
    COLLISION_REASON,
    QUOTA_REASON,
    adopt_pending_membership,
)
from apps.makerspaces.models import (
    ImportedUserReconciliation,
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MakerspaceWaiver,
    PendingImportedMembership,
)
from apps.makerspaces.waiver_state import acceptance_on_file, current_acceptance

pytestmark = pytest.mark.django_db


def user(name, **values):
    return User.objects.create_user(
        username=name,
        email=f"{name}@example.test",
        password="password",
        email_verified_at=timezone.now(),
        **values,
    )


def space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def snapshot(source_id, username=None):
    username = username or f"source-{source_id}"
    return {
        "actor_username": username,
        "actor_display": f"Source actor {source_id}",
        "source_user_id": str(source_id),
        "recorded_at": "2026-08-16T10:00:00Z",
    }


def pending(makerspace, target, source_id="source-membership-1", **values):
    defaults = {
        "makerspace": makerspace,
        "email": target.email.upper(),
        "archived_role_label": "Space Manager",
        "receives_notifications": False,
        "can_refer": False,
        "can_verify": True,
        "created_at": timezone.now() - timedelta(days=500),
        "source_membership_id": source_id,
    }
    defaults.update(values)
    return PendingImportedMembership.objects.create(**defaults)


def member(makerspace, target):
    role = MakerspaceRole.objects.get(makerspace=makerspace, slug="member")
    return MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=target,
        assigned_role=role,
        role=MakerspaceMembership.Role.CUSTOM,
    )


def test_adoption_is_lossless_but_forces_all_four_member_authority_defaults():
    makerspace = space("lossless-adoption")
    target = user("adopted-person")
    actor = user("reconciled-source-actor")
    waiver = MakerspaceWaiver.objects.create(
        makerspace=makerspace,
        version="v7",
        body="Private legal text",
        is_active=True,
    )
    now = timezone.now()
    imported = pending(
        makerspace,
        target,
        verified_at=now - timedelta(days=400),
        verified_actor_snapshot=snapshot("verified"),
        status="revoked",
        activated_at=now - timedelta(days=450),
        activated_actor_snapshot=snapshot("activated"),
        revoked_at=now - timedelta(days=20),
        revoked_actor_snapshot=snapshot("revoked"),
        revocation_reason="private source reason",
        accepted_waiver=waiver,
        waiver_version_accepted=waiver.version,
        waiver_accepted_at=now - timedelta(days=300),
        witnessed_waiver=waiver,
        witnessed_waiver_version=waiver.version,
        witnessed_actor_snapshot=snapshot("witnessed"),
        witnessed_at=now - timedelta(days=200),
    )
    for source_id in ("verified", "activated", "revoked"):
        ImportedUserReconciliation.objects.create(
            makerspace=makerspace,
            source_user_id=source_id,
            source_username=f"source-{source_id}",
            target_user=actor,
        )

    adopted = adopt_pending_membership(target, imported)

    adopted.refresh_from_db()
    imported.refresh_from_db()
    assert adopted.assigned_role.slug == "member"
    assert adopted.role == MakerspaceMembership.Role.CUSTOM
    assert adopted.can_verify is False
    assert adopted.can_refer is True
    assert adopted.receives_notifications is True
    assert adopted.verified_at == imported.verified_at
    assert adopted.verified_by == actor
    assert adopted.verified_actor_snapshot == imported.verified_actor_snapshot
    assert adopted.status == "revoked"
    assert adopted.activated_at == imported.activated_at
    assert adopted.activated_by == actor
    assert adopted.revoked_at == imported.revoked_at
    assert adopted.revoked_by == actor
    assert adopted.revocation_reason == imported.revocation_reason
    assert adopted.accepted_waiver == waiver
    assert adopted.waiver_version_accepted == waiver.version
    assert adopted.waiver_accepted_at == imported.waiver_accepted_at
    assert adopted.witnessed_waiver == waiver
    assert adopted.witnessed_by is None
    assert adopted.witnessed_actor_snapshot == snapshot("witnessed")
    assert adopted.witnessed_at == imported.witnessed_at
    assert adopted.created_at == imported.created_at
    assert acceptance_on_file(adopted) is True
    assert current_acceptance(adopted, active_waiver=waiver) is True
    assert imported.adopted_membership == adopted
    assert imported.adopted_at is not None
    assert imported.unresolved_reason == ""
    audit = AuditLog.objects.get(action="membership.adopted_from_import")
    assert audit.meta == {
        "source_membership_id": imported.source_membership_id,
        "waiver_acceptance": "imported",
    }
    assert waiver.body not in str(audit.meta)
    assert imported.revocation_reason not in str(audit.meta)


def test_adoption_is_idempotent_and_emits_one_audit_event():
    makerspace = space("idempotent-adoption")
    target = user("idempotent-target")
    imported = pending(makerspace, target)

    first = adopt_pending_membership(target, imported)
    second = adopt_pending_membership(target, imported)

    assert first == second
    assert MakerspaceMembership.objects.filter(
        makerspace=makerspace, user=target
    ).count() == 1
    assert AuditLog.objects.filter(action="membership.adopted_from_import").count() == 1


def test_collision_keeps_existing_membership_and_marks_pending_unresolved():
    makerspace = space("collision-adoption")
    target = user("collision-target")
    existing = member(makerspace, target)
    existing.can_verify = True
    existing.save(update_fields=["can_verify"])
    imported = pending(makerspace, target)

    assert adopt_pending_membership(target, imported) is None

    imported.refresh_from_db()
    existing.refresh_from_db()
    assert imported.unresolved_reason == COLLISION_REASON
    assert imported.adopted_membership is None
    assert existing.can_verify is True
    assert MakerspaceMembership.objects.filter(
        makerspace=makerspace, user=target
    ).count() == 1
    assert not AuditLog.objects.filter(action="membership.adopted_from_import").exists()


@override_settings(PLATFORM_DOMAIN_SUFFIX=".space-works.test")
def test_quota_failure_persists_unresolved_without_touching_account():
    makerspace = space("quota-adoption")
    makerspace.resource_limit_overrides = {"members": 0}
    makerspace.save(update_fields=["resource_limit_overrides"])
    target = user("quota-target")
    verified_at = target.email_verified_at
    imported = pending(makerspace, target)

    assert adopt_pending_membership(target, imported) is None

    imported.refresh_from_db()
    target.refresh_from_db()
    assert imported.unresolved_reason == QUOTA_REASON
    assert imported.adopted_membership is None
    assert target.email == "quota-target@example.test"
    assert target.email_verified_at == verified_at
    assert User.objects.filter(pk=target.pk).count() == 1
    assert not MakerspaceMembership.objects.filter(
        makerspace=makerspace, user=target
    ).exists()


@pytest.mark.parametrize("disabled_module", ["membership", "accounts"])
def test_adoption_ignores_optional_module_switches(disabled_module):
    makerspace = space(f"{disabled_module}-off-adoption")
    makerspace.enabled_modules = [
        key for key in makerspace.enabled_modules if key != disabled_module
    ]
    makerspace.save(update_fields=["enabled_modules"])
    target = user(f"{disabled_module}-off-target")
    imported = pending(makerspace, target)

    adopted = adopt_pending_membership(target, imported)

    assert adopted is not None
    assert adopted.assigned_role.slug == "member"


def test_unverified_or_wrong_address_cannot_adopt():
    makerspace = space("address-proof-adoption")
    target = user("proof-target")
    wrong = user("wrong-target")
    imported = pending(makerspace, target)
    target.email_verified_at = None
    target.save(update_fields=["email_verified_at"])

    with pytest.raises(ValidationError, match="verified matching email"):
        adopt_pending_membership(target, imported)
    with pytest.raises(ValidationError, match="verified matching email"):
        adopt_pending_membership(wrong, imported)

    assert not MakerspaceMembership.objects.filter(makerspace=makerspace).exists()


def test_email_confirmation_automatically_discovers_and_adopts_pending_rows():
    makerspace = space("confirmation-adoption")
    target = User.objects.create_user(
        username="confirmation-target",
        email="confirmation-target@example.test",
    )
    imported = pending(makerspace, target)
    EmailVerificationChallenge.objects.create(
        user=target,
        email=target.email,
        code_digest=services_registration._digest("123456"),
        expires_at=timezone.now() + timedelta(minutes=10),
    )

    services_registration.confirm_challenge(target, "123456")

    imported.refresh_from_db()
    target.refresh_from_db()
    assert target.email_verified_at is not None
    assert imported.adopted_membership.user == target


@override_settings(PLATFORM_DOMAIN_SUFFIX=".space-works.test")
def test_confirmation_stays_successful_when_adoption_hits_quota():
    makerspace = space("confirmation-quota-adoption")
    makerspace.resource_limit_overrides = {"members": 0}
    makerspace.save(update_fields=["resource_limit_overrides"])
    target = User.objects.create_user(
        username="confirmation-quota-target",
        email="confirmation-quota-target@example.test",
    )
    imported = pending(makerspace, target)
    EmailVerificationChallenge.objects.create(
        user=target,
        email=target.email,
        code_digest=services_registration._digest("123456"),
        expires_at=timezone.now() + timedelta(minutes=10),
    )

    services_registration.confirm_challenge(target, "123456")

    imported.refresh_from_db()
    target.refresh_from_db()
    assert target.email_verified_at is not None
    assert imported.unresolved_reason == QUOTA_REASON
    assert imported.adopted_membership is None
