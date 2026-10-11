import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.machines.access import is_active_member
from apps.makerspaces import membership_services
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole, MembershipRequest


def user(name, verified=True):
    value = User.objects.create_user(username=name, email=f"{name}@example.test", password="password")
    if verified:
        value.email_verified_at = timezone.now()
        value.save(update_fields=["email_verified_at"])
    return value


@pytest.mark.django_db(transaction=True)
def test_verified_request_then_reactivation_reuses_membership():
    space = Makerspace.objects.create(name="Membership", slug="membership")
    actor, member = user("manager"), user("member")
    actor.is_superuser = True; actor.save(update_fields=["is_superuser"])
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    outcome = membership_services.request_membership(member, space)
    request = MembershipRequest.objects.get(pk=outcome["request_id"])
    membership = membership_services.approve_request(actor, request, role)
    membership_services.revoke_membership(actor, membership, "expired")
    next_outcome = membership_services.request_membership(member, space)
    next_request = MembershipRequest.objects.get(pk=next_outcome["request_id"])
    restored = membership_services.approve_request(actor, next_request, role)
    assert restored.pk == membership.pk
    assert restored.status == "active"
    assert MakerspaceMembership.objects.filter(makerspace=space, user=member).count() == 1


@pytest.mark.django_db(transaction=True)
def test_manager_cannot_revoke_a_peer_manager_but_superadmin_can():
    space = Makerspace.objects.create(name="Peers", slug="peers")
    sm_role = MakerspaceRole.objects.get(makerspace=space, slug="space_manager")
    actor, target = user("mgr-a"), user("mgr-b")
    MakerspaceMembership.objects.create(makerspace=space, user=actor, assigned_role=sm_role, role="space_manager", status="active")
    target_m = MakerspaceMembership.objects.create(makerspace=space, user=target, assigned_role=sm_role, role="space_manager", status="active")
    with pytest.raises(PermissionDenied):
        membership_services.revoke_membership(actor, target_m)
    root = user("root"); root.is_superuser = True; root.save(update_fields=["is_superuser"])
    assert membership_services.revoke_membership(root, target_m).status == "revoked"


@pytest.mark.django_db(transaction=True)
def test_revoked_membership_is_not_an_active_machine_member():
    space = Makerspace.objects.create(name="Ops", slug="ops")
    member_role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    member = user("op")
    membership = MakerspaceMembership.objects.create(makerspace=space, user=member, assigned_role=member_role, role="custom", status="active")
    assert is_active_member(member, space.id) is True
    membership.status = "revoked"; membership.save(update_fields=["status"])
    assert is_active_member(member, space.id) is False


@pytest.mark.django_db(transaction=True)
def test_manager_can_approve_unverified_account_escape_hatch():
    # Self-host / no-SMTP: a manager manually activates a member whose email was never
    # verified (they could not receive an OTP). Self-request still requires verification,
    # but manager approval must not.
    space = Makerspace.objects.create(name="Escape", slug="escape")
    actor, member = user("chief"), user("nosmtp", verified=False)
    actor.is_superuser = True; actor.save(update_fields=["is_superuser"])
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    invite = membership_services.invite_membership(actor, space, member.email, role)
    membership = membership_services.approve_request(actor, invite, role)
    assert membership.status == "active"
    assert member.email_verified_at is None


@pytest.mark.django_db(transaction=True)
def test_unverified_user_cannot_request_and_cross_space_role_is_rejected():
    one = Makerspace.objects.create(name="One", slug="one")
    two = Makerspace.objects.create(name="Two", slug="two")
    actor, member = user("boss"), user("unverified", verified=False)
    actor.is_superuser = True; actor.save(update_fields=["is_superuser"])
    with pytest.raises(ValidationError):
        membership_services.request_membership(member, one)
    member.email_verified_at = timezone.now(); member.save(update_fields=["email_verified_at"])
    outcome = membership_services.request_membership(member, one)
    request = MembershipRequest.objects.get(pk=outcome["request_id"])
    with pytest.raises(ValidationError):
        membership_services.approve_request(actor, request, MakerspaceRole.objects.get(makerspace=two, slug="member"))
    assert request.state == MembershipRequest.State.REQUESTED
