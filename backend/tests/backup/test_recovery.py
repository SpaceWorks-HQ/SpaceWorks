from datetime import timedelta

import pytest
from django.contrib.sessions.models import Session
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.tokens import SpaceWorksRefreshToken, validate_auth_generation
from apps.apiclients.models import ApiClient
from apps.audit.models import AuditLog
from apps.backup.models import (
    BackupArchive,
    DeploymentRecoveryState,
    MakerspaceArchiveCustodyState,
    MakerspaceArchiveRecipient,
    RestoreOperation,
)
from apps.backup.recovery import (
    RESIDUAL_RISK,
    acknowledge_quarantine,
    assert_principal_allowed,
    enter_quarantine,
    set_recovery_principal,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership


pytestmark = pytest.mark.django_db


def recovery_fixture():
    admin = User.objects.create_superuser(
        username="recovery-admin", email="recovery@example.org", password="before"
    )
    other = User.objects.create_user(username="ordinary", password="before")
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        requested_by=admin,
        status=BackupArchive.Status.AVAILABLE,
        object_key="backup-archives/deployment/recovery.tar.age",
        age_encrypted=True,
        expires_at=timezone.now() + timedelta(days=1),
    )
    restore = RestoreOperation.objects.create(
        archive=archive,
        kind=RestoreOperation.Kind.DISASTER,
        requested_by=admin,
    )
    return admin, other, restore


def authenticated(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_quarantine_rotates_generation_and_tears_down_credentials():
    admin, other, restore = recovery_fixture()
    old_access = SpaceWorksRefreshToken.for_user(other).access_token
    api_client = ApiClient.objects.create(
        label="restored client",
        secret_encrypted=b"opaque",
        allowed_origins=["https://example.org"],
        created_by=admin,
    )
    Session.objects.create(
        session_key="restored-session",
        session_data="e30=",
        expire_date=timezone.now() + timedelta(days=1),
    )
    previous_generation = DeploymentRecoveryState.load().auth_generation

    state = enter_quarantine(restore, "disaster restore")

    assert state.mode == DeploymentRecoveryState.Mode.QUARANTINED
    assert state.auth_generation != previous_generation
    assert not Session.objects.exists()
    api_client.refresh_from_db()
    assert api_client.is_active is False
    admin.refresh_from_db()
    other.refresh_from_db()
    assert not admin.has_usable_password()
    assert not other.has_usable_password()
    with pytest.raises(AuthenticationFailed):
        validate_auth_generation(old_access)
    assert AuditLog.objects.filter(action="backup.restore_quarantined").exists()


def test_only_durable_recovery_principal_can_authenticate_and_acknowledge():
    admin, other, restore = recovery_fixture()
    enter_quarantine(restore, "disaster restore")

    with pytest.raises(AuthenticationFailed):
        assert_principal_allowed(admin)
    recovered = set_recovery_principal(admin, "one-time-recovery-password")
    assert_principal_allowed(recovered)
    with pytest.raises(AuthenticationFailed):
        assert_principal_allowed(other)
    with pytest.raises(PermissionDenied):
        acknowledge_quarantine(other, RESIDUAL_RISK)
    with pytest.raises(ValidationError, match="match exactly"):
        acknowledge_quarantine(recovered, RESIDUAL_RISK + " ")

    state = acknowledge_quarantine(recovered, RESIDUAL_RISK)

    assert state.mode == DeploymentRecoveryState.Mode.NORMAL
    assert state.recovery_principal_id == recovered.pk
    assert state.acknowledged_by_id == recovered.pk
    assert state.acknowledgement == RESIDUAL_RISK
    assert AuditLog.objects.filter(action="backup.quarantine_acknowledged").exists()


def test_acknowledgement_records_below_floor_custody_inside_transaction():
    admin, _other, restore = recovery_fixture()
    makerspace = Makerspace.objects.create(
        name="Restored degraded",
        slug="restored-degraded",
        superadmin_access_enabled=False,
    )
    MakerspaceArchiveRecipient.objects.create(
        makerspace=makerspace,
        public_recipient="age1restoreddegraded",
        fingerprint="9" * 64,
        label="Only restored custodian",
        verified_at=timezone.now(),
    )
    enter_quarantine(restore, "disaster restore")
    recovered = set_recovery_principal(admin, "one-time-recovery-password")

    state = acknowledge_quarantine(recovered, RESIDUAL_RISK)

    custody = MakerspaceArchiveCustodyState.objects.get(makerspace=makerspace)
    assert state.mode == DeploymentRecoveryState.Mode.NORMAL
    assert custody.state == custody.State.DEGRADED_ONE_RECIPIENT
    assert custody.alarm_episode == 1


def test_recovery_state_is_limited_to_superadmin_or_recovery_principal():
    admin, member, restore = recovery_fixture()
    url = reverse("backup-recovery-state")
    makerspace = Makerspace.objects.create(name="Recovery scope", slug="recovery-scope")
    MakerspaceMembership.objects.create(user=member, makerspace=makerspace)
    staff = User.objects.create_user(
        username="recovery-staff",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=staff,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )

    assert authenticated(member).get(url).status_code == 403
    assert authenticated(staff).get(url).status_code == 403
    assert authenticated(admin).get(url).status_code == 200

    enter_quarantine(restore, "disaster restore")
    principal = set_recovery_principal(admin, "one-time-recovery-password")
    principal_client = authenticated(principal)

    assert principal_client.get(url).status_code == 200
    acknowledged = principal_client.post(
        url, {"acknowledgement": RESIDUAL_RISK}, format="json"
    )
    assert acknowledged.status_code == 200
    assert acknowledged.data["mode"] == DeploymentRecoveryState.Mode.NORMAL
