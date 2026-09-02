from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import close_old_connections
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.organizations import governance
from apps.organizations import services_invitations
from apps.organizations.exceptions import InvitationRedeemed, InvitationRevoked
from apps.organizations.models import Organization, OrganizationInvitation, OrganizationMembership


pytestmark = pytest.mark.django_db


def user(slug):
    return User.objects.create_user(
        username=slug,
        email=f"{slug}@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )


def client(actor):
    result = APIClient()
    result.force_authenticate(actor)
    return result


def setup_manager():
    org = Organization.objects.create(name="Governed Org", slug="governed-org")
    actor = user("org-governor")
    OrganizationMembership.objects.create(
        organization=org,
        user=actor,
        governance_actions=[
            governance.MANAGE_ORGANIZATION_MEMBERS,
            governance.MANAGE_ORGANIZATION_PROFILE,
        ],
        granted_actions=[rbac.Action.MANAGE_EVENTS],
    )
    return org, actor


def create_invitation(org, actor, **overrides):
    payload = {
        "governance_actions": [governance.MANAGE_ORGANIZATION_PROFILE],
        "granted_actions": [rbac.Action.MANAGE_EVENTS],
        "expires_in_days": 7,
        **overrides,
    }
    return client(actor).post(
        reverse("admin-organization-invitations", kwargs={"pk": org.pk}),
        payload,
        format="json",
    )


def test_invitation_token_is_returned_once_stored_as_digest_and_never_audited():
    org, actor = setup_manager()
    response = create_invitation(org, actor)

    assert response.status_code == 201
    token = response.data["token"]
    invitation = OrganizationInvitation.objects.get(pk=response.data["id"])
    assert invitation.token_digest != token
    assert len(invitation.token_digest) == 64
    audit = AuditLog.objects.get(action="organization.invitation_created")
    assert token not in str(audit.meta)
    listed = client(actor).get(
        reverse("admin-organization-invitations", kwargs={"pk": org.pk})
    )
    assert "token" not in listed.data["results"][0]
    assert "token_digest" not in listed.data["results"][0]


def test_governance_only_account_can_open_central_staff_session():
    _org, actor = setup_manager()
    actor.set_password("central-governance-password")
    actor.save(update_fields=["password"])

    response = APIClient().post(
        reverse("auth-login"),
        {
            "username": actor.username,
            "password": "central-governance-password",
            "surface": "staff",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["surface"] == "staff_api"
    assert response.data["user"]["makerspaces"] == []


def test_redeem_is_single_use_and_creates_exact_authority_projection():
    org, actor = setup_manager()
    invite = create_invitation(org, actor)
    recipient = user("org-recipient")
    url = reverse("auth-organization-invitation-redeem")

    redeemed = client(recipient).post(url, {"token": invite.data["token"]}, format="json")
    repeated = client(recipient).post(url, {"token": invite.data["token"]}, format="json")

    assert redeemed.status_code == 200
    membership = OrganizationMembership.objects.get(organization=org, user=recipient)
    assert membership.governance_actions == [governance.MANAGE_ORGANIZATION_PROFILE]
    assert membership.granted_actions == [rbac.Action.MANAGE_EVENTS]
    assert repeated.status_code == 409
    assert AuditLog.objects.filter(action="organization.invitation_redeemed").count() == 1


def test_malformed_unknown_and_expired_tokens_have_stable_statuses():
    org, actor = setup_manager()
    url = reverse("auth-organization-invitation-redeem")
    recipient_client = client(user("invalid-token-recipient"))

    assert recipient_client.post(url, {"token": "short"}, format="json").status_code == 400
    assert recipient_client.post(url, {"token": "x" * 32}, format="json").status_code == 404

    created = create_invitation(org, actor)
    OrganizationInvitation.objects.filter(pk=created.data["id"]).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    expired = recipient_client.post(url, {"token": created.data["token"]}, format="json")
    assert expired.status_code == 409
    assert expired.data["code"] == "invitation_expired"


def test_inviter_cannot_escalate_and_redeem_rechecks_changed_grants():
    org, actor = setup_manager()
    escalation = create_invitation(org, actor, granted_actions=[rbac.Action.EDIT_INVENTORY])
    assert escalation.status_code == 403

    invite = create_invitation(org, actor)
    manager = OrganizationMembership.objects.get(organization=org, user=actor)
    manager.granted_actions = []
    manager.save(update_fields=["granted_actions"])
    response = client(user("late-recipient")).post(
        reverse("auth-organization-invitation-redeem"),
        {"token": invite.data["token"]},
        format="json",
    )
    assert response.status_code == 409
    assert response.data["code"] == "invitation_grant_changed"


def test_suspended_membership_is_not_reactivated_and_revocation_wins_before_redeem():
    org, actor = setup_manager()
    recipient = user("suspended-recipient")
    suspended = OrganizationMembership.objects.create(
        organization=org,
        user=recipient,
        status=OrganizationMembership.Status.SUSPENDED,
    )
    first = create_invitation(org, actor)
    assert client(recipient).post(
        reverse("auth-organization-invitation-redeem"),
        {"token": first.data["token"]},
        format="json",
    ).status_code == 409
    suspended.refresh_from_db()
    assert suspended.status == OrganizationMembership.Status.SUSPENDED

    second = create_invitation(org, actor)
    assert client(actor).delete(
        reverse("admin-organization-invitation-revoke", kwargs={"pk": second.data["id"]})
    ).status_code == 204
    assert client(user("revoked-recipient")).post(
        reverse("auth-organization-invitation-redeem"),
        {"token": second.data["token"]},
        format="json",
    ).status_code == 409


@pytest.mark.django_db(transaction=True)
def test_concurrent_redemption_consumes_token_and_applies_membership_once():
    org, actor = setup_manager()
    invitation, token = services_invitations.create_invitation(
        org,
        actor=actor,
        governance_actions=[governance.MANAGE_ORGANIZATION_PROFILE],
        granted_actions=[rbac.Action.MANAGE_EVENTS],
    )
    recipient = user("concurrent-recipient")
    gate = Barrier(2)

    def redeem():
        close_old_connections()
        gate.wait()
        try:
            services_invitations.redeem_invitation(
                token, actor=User.objects.get(pk=recipient.pk)
            )
            return "redeemed"
        except InvitationRedeemed:
            return "already-redeemed"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(lambda _item: redeem(), range(2)))

    invitation.refresh_from_db()
    assert outcomes == ["already-redeemed", "redeemed"]
    assert invitation.redeemed_by_id == recipient.pk
    assert OrganizationMembership.objects.filter(
        organization=org, user=recipient
    ).count() == 1
    assert AuditLog.objects.filter(action="organization.invitation_redeemed").count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_revoke_and_redeem_have_one_coherent_winner():
    org, actor = setup_manager()
    invitation, token = services_invitations.create_invitation(
        org,
        actor=actor,
        governance_actions=[governance.MANAGE_ORGANIZATION_PROFILE],
        granted_actions=[],
    )
    recipient = user("race-recipient")
    gate = Barrier(2)

    def revoke():
        close_old_connections()
        gate.wait()
        try:
            services_invitations.revoke_invitation(
                OrganizationInvitation.objects.get(pk=invitation.pk),
                actor=User.objects.get(pk=actor.pk),
            )
            return "revoked"
        except InvitationRedeemed:
            return "redeem-won"
        finally:
            close_old_connections()

    def redeem():
        close_old_connections()
        gate.wait()
        try:
            services_invitations.redeem_invitation(
                token, actor=User.objects.get(pk=recipient.pk)
            )
            return "redeemed"
        except InvitationRevoked:
            return "revoke-won"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(revoke), pool.submit(redeem))
        outcomes = {future.result() for future in futures}

    invitation.refresh_from_db()
    membership_exists = OrganizationMembership.objects.filter(
        organization=org, user=recipient
    ).exists()
    assert outcomes in ({"revoked", "revoke-won"}, {"redeemed", "redeem-won"})
    assert membership_exists is (invitation.redeemed_at is not None)
    assert (invitation.revoked_at is None) != (invitation.redeemed_at is None)
