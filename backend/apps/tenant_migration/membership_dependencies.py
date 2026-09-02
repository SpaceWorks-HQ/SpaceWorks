"""Literal classification of rows that cannot survive without a membership."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MembershipDependency:
    retained_by_import: bool
    reason: str

MEMBERSHIP_DEPENDENT_MODELS = {
    "accounts.MemberClaimCode": MembershipDependency(
        retained_by_import=False,
        reason="Transient claim credentials are omitted from tenant archives.",
    ),
    "events.MemberCalendarFeed": MembershipDependency(
        retained_by_import=False,
        reason=(
            "A deployment-local bearer credential over the member's registration history. "
            "It is already omitted from tenant archives, so a restored tenant reissues it "
            "rather than carrying a live subscribable token across deployments."
        ),
    ),
    "makerspaces.MemberProfile": MembershipDependency(
        retained_by_import=True,
        reason="A member profile is owned by one non-null makerspace membership.",
    ),
    "presence.PresenceSession": MembershipDependency(
        retained_by_import=True,
        reason="Presence retains its non-null protected membership attribution.",
    ),
}
