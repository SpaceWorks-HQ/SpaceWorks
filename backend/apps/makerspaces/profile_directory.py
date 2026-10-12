"""The member-visible directory: who opted in, and one other member's visible profile."""

from django.db.models import Q

from apps.inventory import public_image_storage
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.profile_services import display_name_for, read_profile


def directory(makerspace, query=""):
    """Visible profiles, plus a count of everyone who did not opt in.

    ``query`` matches the plain-text identity columns only (username, display name, profile
    headline and institution). Contact fields are scoped PII and are never searched here.
    """
    memberships = MakerspaceMembership.objects.filter(
        makerspace=makerspace, status="active", user__is_active=True
    ).select_related("user", "profile")
    query = (query or "").strip()[:200]
    if query:
        memberships = memberships.filter(
            Q(user__username__icontains=query)
            | Q(user__display_name__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(profile__headline__icontains=query)
            | Q(profile__institution__icontains=query)
        )
    members, hidden = [], 0
    for membership in memberships:
        profile = getattr(membership, "profile", None)
        # No profile row at all is the same answer as one that is not visible: nobody
        # is listed until they choose to be.
        if profile is None or not profile.is_visible:
            hidden += 1
            continue
        members.append(
            {
                "membership_id": membership.pk,
                "display_name": display_name_for(membership),
                "headline": profile.headline,
                "avatar_url": public_image_storage.public_url(profile.avatar_key) or None,
            }
        )
    members.sort(key=lambda row: row["display_name"].lower())
    return {"members": members, "hidden_count": hidden}


def visible_profile(makerspace, membership_id, *, local_activity_only=False):
    """One other member's profile, or None when it is not theirs to see."""
    membership = MakerspaceMembership.objects.select_related("user", "profile").filter(
        pk=membership_id, makerspace=makerspace, status="active", user__is_active=True
    ).first()
    if membership is None:
        return None
    profile = getattr(membership, "profile", None)
    if profile is None or not profile.is_visible:
        return None
    return read_profile(membership, local_activity_only=local_activity_only)
