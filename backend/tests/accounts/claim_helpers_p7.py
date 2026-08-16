"""Real issue/redeem helpers shared by the Phase 7 claim acceptance tests."""

from dataclasses import dataclass

from rest_framework.test import APIClient

from apps.accounts.models import MemberClaimCode, User
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.platform import module_enabled
from apps.presence.models import PresenceSession
from tests.handout_roles import make_handout_member


@dataclass
class ClaimHarness:
    space: Makerspace
    staff: User
    member: User
    membership: MakerspaceMembership
    claim: MemberClaimCode
    staff_client: APIClient
    claim_client: APIClient


def redeemed_claim(suffix: str) -> ClaimHarness:
    """Issue and redeem a physical code while the accounts module is disabled."""
    space = Makerspace.objects.create(name=f"Claim {suffix}", slug=f"claim-{suffix}")
    space.enabled_modules = [
        key for key in space.enabled_modules if key != "accounts"
    ]
    space.save(update_fields=["enabled_modules", "updated_at"])
    assert not module_enabled(space, "accounts")

    staff = make_handout_member(f"claim-staff-{suffix}", space)
    member = User(
        username=f"claim-member-{suffix}",
        display_name=f"Walk-in {suffix}",
        email=f"walk-in-{suffix}@example.test",
        phone="+15550101010",
        is_walk_in=True,
        is_active=True,
        access_status=User.AccessStatus.ACTIVE,
    )
    member.set_unusable_password()
    member.save()
    membership = MakerspaceMembership.objects.create(
        makerspace=space,
        user=member,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
    )

    staff_client = APIClient()
    staff_client.force_authenticate(staff)
    issued = staff_client.post(
        f"/api/v1/admin/makerspaces/{space.pk}/member-claim-codes",
        {"membership_id": membership.pk},
        format="json",
    )
    assert issued.status_code == 201, issued.data

    claim_client = APIClient(REMOTE_ADDR="203.0.113.70")
    redeemed = claim_client.post(
        "/api/v1/auth/claim/redeem",
        {"makerspace_slug": space.slug, "code": issued.data["code"]},
        format="json",
    )
    assert redeemed.status_code == 200, redeemed.data
    claim_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {redeemed.data['access']}"
    )
    claim = MemberClaimCode.objects.get(pk=issued.data["id"])
    return ClaimHarness(
        space, staff, member, membership, claim, staff_client, claim_client
    )


def start_claim_presence(harness: ClaimHarness, duration_minutes: int = 60):
    response = harness.claim_client.post(
        f"/api/v1/public/{harness.space.slug}/presence-sessions",
        {"duration_minutes": duration_minutes},
        format="json",
    )
    assert response.status_code == 201, response.data
    session = PresenceSession.objects.get(
        created_via_claim_session=harness.claim,
        ended_at__isnull=True,
    )
    assert session.member == harness.member
    assert session.makerspace == harness.space
    assert session.expires_at <= harness.claim.absolute_expires_at
    return session
