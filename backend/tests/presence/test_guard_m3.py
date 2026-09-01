import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.waiver_services import accept_waiver, publish_waiver
from apps.presence import services
from apps.presence.guard import (
    MemberPresenceRequired,
    PresenceRequired,
    WaiverAcceptanceRequired,
    require_active_account,
    require_active_member_presence,
)


def setup_member(space):
    user = User.objects.create_user(username="guard-member", email="guard@example.test", password="password")
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    membership = MakerspaceMembership.objects.create(makerspace=space, user=user, assigned_role=role, role="custom")
    return user, membership


@pytest.mark.django_db
def test_active_account_guard_keeps_identity_checks_without_requiring_membership():
    space = Makerspace.objects.create(name="Account Guard", slug="account-guard")
    user = User.objects.create_user(username="account-only", password="password")

    result = require_active_account(user, space)

    assert result.membership is None
    assert result.accepted_waiver is None
    assert result.session is None

    user.access_status = User.AccessStatus.RESTRICTED
    user.save(update_fields=["access_status"])
    with pytest.raises(MemberPresenceRequired):
        require_active_account(user, space)


@pytest.mark.django_db
def test_guard_has_stable_membership_waiver_and_presence_contract():
    space = Makerspace.objects.create(name="Guard", slug="guard")
    user, membership = setup_member(space)
    with pytest.raises(MemberPresenceRequired) as missing:
        require_active_member_presence(User(), space)
    assert missing.value.code == "membership_required"
    waiver = publish_waiver(user, space, "Terms", "v1")
    with pytest.raises(WaiverAcceptanceRequired) as unaccepted:
        require_active_member_presence(user, space)
    assert unaccepted.value.code == "waiver_acceptance_required"
    accept_waiver(membership)
    with pytest.raises(PresenceRequired) as absent:
        require_active_member_presence(user, space)
    assert absent.value.code == "presence_required"
    services.start_session(user, space, 60)
    assert require_active_member_presence(user, space).accepted_waiver.pk == waiver.pk


@pytest.mark.django_db
def test_guard_accepts_current_staff_witnessed_waiver_evidence():
    space = Makerspace.objects.create(name="Witness Guard", slug="witness-guard")
    user, membership = setup_member(space)
    staff = User.objects.create_user(username="witness", password="password")
    waiver = publish_waiver(staff, space, "Terms", "v1")
    MakerspaceMembership.objects.filter(pk=membership.pk).update(
        witnessed_waiver=waiver,
        witnessed_waiver_version=waiver.version,
        witnessed_by=staff,
        witnessed_at=timezone.now(),
    )
    services.start_session(user, space, 60)

    result = require_active_member_presence(user, space)

    assert result.accepted_waiver.pk == waiver.pk
