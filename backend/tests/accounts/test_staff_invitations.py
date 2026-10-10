from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import User
from apps.accounts.models_staff_invitations import StaffInvitation
from apps.accounts.staff_invitation_acceptance import GENERIC_ERROR
from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from tests.accounts.mfa_helpers import enrolled
from apps.accounts.mfa_crypto import recovery_codes

pytestmark = pytest.mark.django_db
PASSWORD = "Invited staff password 394!"
ACCEPT = "/api/v1/auth/staff-invitations/accept"


@pytest.fixture
def invitations(settings):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode()
    settings.PUBLIC_APP_BASE_URL = "https://app.example.test"
    space = Makerspace.objects.create(name="Invite space", slug="invite-space")
    actor = User.objects.create_user(username="inviter", password=PASSWORD)
    MakerspaceMembership.objects.create(user=actor, makerspace=space, role="space_manager")
    role = MakerspaceRole.objects.get(makerspace=space, slug="inventory_manager")
    client = APIClient()
    client.force_authenticate(actor)
    return space, actor, role, client


def base(space):
    return f"/api/v1/admin/makerspaces/{space.pk}/staff-invitations"


def invite(data, email="invited@example.test"):
    space, _, role, client = data
    response = client.post(base(space), {"email": email, "role_id": role.pk}, format="json")
    assert response.status_code == 201
    fragment = parse_qs(urlsplit(response.data["accept_url"]).fragment)
    return StaffInvitation.objects.get(pk=response.data["id"]), fragment["token"][0], response


def accept(space, token, password=PASSWORD, code=""):
    return APIClient().post(ACCEPT, {"token": token, "makerspace_slug": space.slug,
                                   "password": password, "code": code}, format="json")


def test_email_off_yields_copyable_link_and_new_account_membership(invitations):
    space, actor, role, _ = invitations
    space.enabled_modules = [key for key in space.enabled_modules if key != "email"]
    space.save(update_fields=["enabled_modules"])
    row, token, created = invite(invitations)
    assert created.data["delivery_status"] in {"skipped", "unavailable"}
    assert created.data["accept_url"].startswith("https://app.example.test/staff-invitations/accept#")
    assert row.token_digest != token and row.email_ciphertext.startswith("fernet:")
    accepted = accept(space, token)
    assert accepted.status_code == 200
    assert "access" not in accepted.data and "refresh" not in accepted.data
    user = User.objects.get(email=row.email)
    membership = MakerspaceMembership.objects.get(user=user, makerspace=space)
    assert membership.assigned_role == role and membership.status == "active"
    assert user.email_verified_at and user.check_password(PASSWORD)
    assert AuditLog.objects.filter(action="staff.invitation_created", actor=actor, makerspace=space).exists()
    assert AuditLog.objects.filter(action="staff.invitation_accepted", actor=user, makerspace=space).exists()
    assert accept(space, token).status_code == 400


def test_existing_account_is_linked_without_password_change_or_duplicate(invitations):
    space = invitations[0]
    existing = User.objects.create_user(username="existing-staff", email="invited@example.test", password=PASSWORD)
    _, token, _ = invite(invitations)
    assert accept(space, token).status_code == 200
    existing.refresh_from_db()
    assert existing.check_password(PASSWORD)
    assert User.objects.filter(email=existing.email).count() == 1
    assert MakerspaceMembership.objects.get(user=existing, makerspace=space).assigned_role == invitations[2]


def test_delivery_failure_keeps_invitation_and_link_without_logging_provider_secrets(invitations, monkeypatch, caplog):
    def fail(**kwargs):
        assert kwargs["persist_body"] is False and kwargs["sync"] is True
        raise RuntimeError("smtp-credential-secret")
    monkeypatch.setattr("apps.accounts.staff_invitation_delivery.dispatch_email", fail)
    row, token, response = invite(invitations)
    assert response.data["delivery_status"] == "unavailable"
    assert "smtp-credential-secret" not in caplog.text
    assert accept(invitations[0], token).status_code == 200
    assert row.pk


@pytest.mark.parametrize("state", ["expired", "revoked", "used", "cross_tenant", "unknown"])
def test_unavailable_invitation_has_one_generic_response(invitations, state):
    space = invitations[0]
    row, token, _ = invite(invitations)
    if state == "expired":
        row.expires_at = timezone.now() - timedelta(seconds=1)
    elif state == "revoked":
        row.revoked_at = timezone.now()
    elif state == "used":
        row.accepted_at = timezone.now()
    elif state == "cross_tenant":
        space = Makerspace.objects.create(name="Other", slug="other-invitation")
    else:
        token = "x" * 43
    row.save()
    response = accept(space, token)
    assert response.status_code == 400 and response.json() == {"detail": GENERIC_ERROR}
    assert not User.objects.filter(email="invited@example.test").exists()


def test_resend_rotates_bearer_and_revoke_prevents_acceptance(invitations):
    space, _, _, client = invitations
    row, old_token, _ = invite(invitations)
    resent = client.post(f"{base(space)}/{row.pk}/resend", format="json")
    assert resent.status_code == 200
    token = parse_qs(urlsplit(resent.data["accept_url"]).fragment)["token"][0]
    assert token != old_token
    assert accept(space, old_token).status_code == 400
    revoked = client.post(f"{base(space)}/{row.pk}/revoke", format="json")
    assert revoked.status_code == 200
    assert accept(space, token).status_code == 400
    assert client.post(f"{base(space)}/{row.pk}/resend", format="json").status_code == 400
    assert AuditLog.objects.filter(action="staff.invitation_resent").exists()
    assert AuditLog.objects.filter(action="staff.invitation_revoked").exists()


def test_scoped_lists_and_cross_tenant_role_cannot_grant_authority(invitations):
    space, actor, _, client = invitations
    invite(invitations)
    other = Makerspace.objects.create(name="Private", slug="private-invitations")
    foreign_role = MakerspaceRole.objects.get(makerspace=other, slug="inventory_manager")
    assert client.post(base(space), {"email": "other@example.test", "role_id": foreign_role.pk},
                       format="json").status_code == 400
    assert client.get(base(other)).status_code in {403, 404}
    response = client.get(base(space))
    assert response.status_code == 200 and response.data["count"] == 1
    manager_role = MakerspaceRole.objects.get(makerspace=space, slug="space_manager")
    assert client.post(base(space), {"email": "escalate@example.test", "role_id": manager_role.pk},
                       format="json").status_code == 403


def test_feature_off_answers_400_and_never_sends(invitations, monkeypatch):
    space, _, role, client = invitations
    space.enabled_features = [key for key in space.enabled_features if key != "staff.invitations"]
    space.save(update_fields=["enabled_features"])
    monkeypatch.setattr("apps.accounts.staff_invitation_delivery.dispatch_email",
                        lambda **kwargs: pytest.fail("Disabled invitations cannot send"))
    assert client.get(base(space)).status_code == 400
    assert client.post(base(space), {"email": "other@example.test", "role_id": role.pk},
                       format="json").status_code == 400


def test_custom_handover_role_can_be_invited_and_mfa_enforcement_applies(invitations):
    from apps.accounts.mfa_policy import required
    space, _, _, client = invitations
    space.enabled_features = [*space.enabled_features, "security.staff_mfa_required"]
    space.save(update_fields=["enabled_features"])
    role = MakerspaceRole.objects.create(makerspace=space, name="Front desk", slug="front-desk",
                                         granted_actions=[rbac.Action.ISSUE_REQUEST, rbac.Action.UPLOAD_EVIDENCE])
    response = client.post(base(space), {"email": "desk@example.test", "role_id": role.pk}, format="json")
    assert response.status_code == 201
    token = parse_qs(urlsplit(response.data["accept_url"]).fragment)["token"][0]
    assert accept(space, token).status_code == 200
    user = User.objects.get(email="desk@example.test")
    assert required(user)
    login = APIClient().post("/api/v1/auth/login", {"username": user.email, "password": PASSWORD}, format="json")
    assert login.status_code == 200 and login.data["enrollment_required"]


def test_revoke_does_not_require_permission_to_regrant_a_changed_role(invitations):
    space, _, role, client = invitations
    row, token, _ = invite(invitations)
    role.granted_actions = [rbac.Action.MANAGE_MAKERSPACE]
    role.save(update_fields=["granted_actions"])
    assert client.post(f"{base(space)}/{row.pk}/revoke", format="json").status_code == 200
    assert accept(space, token).status_code == 400


def test_resend_revalidates_against_current_sender(invitations):
    space, creator, _, client = invitations
    row, _, _ = invite(invitations)
    replacement = User.objects.create_user(username="replacement-inviter", password=PASSWORD)
    MakerspaceMembership.objects.create(user=replacement, makerspace=space, role="space_manager")
    MakerspaceMembership.objects.filter(user=creator, makerspace=space).update(status="revoked")
    client.force_authenticate(replacement)
    resent = client.post(f"{base(space)}/{row.pk}/resend", format="json")
    assert resent.status_code == 200
    token = parse_qs(urlsplit(resent.data["accept_url"]).fragment)["token"][0]
    assert accept(space, token).status_code == 200
    row.refresh_from_db()
    assert row.created_by == replacement


@pytest.mark.parametrize("existing", [False, True])
def test_accept_failure_does_not_enumerate_account_and_commits_attempts(invitations, existing):
    space = invitations[0]
    if existing:
        User.objects.create_user(username="enum-existing", email="invited@example.test", password=PASSWORD)
    row, token, _ = invite(invitations)
    for _ in range(6):
        response = accept(space, token, password="weak")
        assert response.status_code == 400 and response.json() == {"detail": GENERIC_ERROR}
    row.refresh_from_db()
    assert row.failed_attempts == 5 and row.accepted_at is None
    assert not MakerspaceMembership.objects.filter(user__email=row.email, makerspace=space).exists()
    assert AuditLog.objects.filter(action="staff.invitation_accept_failed").count() == 6


def test_existing_enrolled_account_must_prove_second_factor(invitations):
    space = invitations[0]
    user = User.objects.create_user(username="secure-existing", email="invited@example.test", password=PASSWORD)
    codes, digests = recovery_codes()
    row, _ = enrolled(user, recovery_digests=digests)
    _, token, _ = invite(invitations)
    assert accept(space, token).status_code == 400
    assert accept(space, token, code=codes[0]).status_code == 200
    row.refresh_from_db()
    assert len(row.recovery_digests) == 9


def test_frozen_tenant_cannot_accept_an_invitation_or_create_an_account(invitations):
    from tests.tenant_migration.source_gate_helpers import close_gate
    space, actor, _, _ = invitations
    _, token, _ = invite(invitations)
    close_gate(space, actor)
    response = accept(space, token)
    assert response.status_code == 423
    assert not User.objects.filter(email="invited@example.test").exists()


@pytest.mark.parametrize("change", ["inviter_revoked", "grants_changed", "tenant_archived", "target_revoked"])
def test_accept_rechecks_current_authority_and_never_reactivates_revoked_users(invitations, change):
    space, actor, role, _ = invitations
    user = User.objects.create_user(username="authority-target", email="invited@example.test", password=PASSWORD)
    _, token, _ = invite(invitations)
    if change == "inviter_revoked":
        MakerspaceMembership.objects.filter(user=actor, makerspace=space).update(status="revoked")
    elif change == "grants_changed":
        role.granted_actions = [rbac.Action.VIEW_INVENTORY]
        role.save(update_fields=["granted_actions"])
    elif change == "tenant_archived":
        space.archived_at = timezone.now()
        space.save(update_fields=["archived_at"])
    else:
        MakerspaceMembership.objects.create(user=user, makerspace=space, role="member", status="revoked")
    assert accept(space, token).json() == {"detail": GENERIC_ERROR}
