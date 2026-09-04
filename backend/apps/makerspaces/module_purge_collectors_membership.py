"""Membership-module purge collectors (profiles, projects, requests, member ID cards).

Split out of `module_purge_collectors` to keep that barrel under the file-size ceiling; the
same two rules apply (only what the module owns; model imports stay function-local).
"""
from apps.makerspaces.module_purge_collectors_single_model import _counts, _delete


def membership_public_image_keys(makerspace):
    """Avatars and project images, collected BEFORE the rows that name them go.

    Without this the objects outlive every row that could name them: nothing else in the
    system knows a `member/<id>/...` key exists once the profile is deleted, so they
    would sit in the bucket forever and keep counting against the space's storage.
    """
    from apps.makerspaces.models import MemberProfile, MemberProject

    keys = list(
        MemberProfile.objects.filter(membership__makerspace=makerspace).values_list(
            "avatar_key", flat=True
        )
    )
    keys += list(
        MemberProject.objects.filter(
            profile__membership__makerspace=makerspace
        ).values_list("image_key", flat=True)
    )
    return [key for key in dict.fromkeys(keys) if key]


def membership_private_keys(makerspace, add):
    """Card photos: private objects deleted with the module (bytes are faces)."""
    from apps.makerspaces.models import MemberCard

    for key in MemberCard.objects.filter(makerspace=makerspace).values_list("photo_object_key", flat=True):
        if key:
            add(key)


def membership_private_key_sizes(makerspace):
    from apps.makerspaces.models import MemberCard

    return {
        key: size or 0
        for key, size in MemberCard.objects.filter(makerspace=makerspace).exclude(photo_object_key="").values_list("photo_object_key", "photo_size_bytes")
    }


def membership_delete(makerspace, cursor):
    from apps.makerspaces.models import (
        InvitationRequest,
        MemberCard,
        MemberProfile,
        MembershipPlan,
        MembershipRequest,
        MembershipTerm,
    )

    # `MakerspaceMembership` itself is core RBAC state and is NEVER deleted here -- the
    # module gates community enrolment/content, not the roster (plan A7). Waivers and
    # both acceptance evidence types are core liability records and likewise survive.
    # Profiles go even though the membership stays: a profile is community content the
    # module owns, not the RBAC state the module deliberately leaves behind. Projects
    # cascade from the profile.
    profiles, profile_labels = _delete(
        MemberProfile.objects.filter(membership__makerspace=makerspace)
    )
    requests, request_labels = _delete(
        MembershipRequest.objects.filter(makerspace=makerspace)
    )
    # Cards go with the module: their QR codes are revoked so historic scans still resolve
    # as revoked, never as an unknown payload.
    from apps.boxes.models import QrCode

    QrCode.objects.filter(
        makerspace=makerspace, target_type=QrCode.TargetType.MEMBER_CARD,
        status=QrCode.Status.ACTIVE,
    ).update(status=QrCode.Status.REVOKED)
    cards, card_labels = _delete(MemberCard.objects.filter(makerspace=makerspace))
    # Terms before plans: a term PROTECTs its plan. Renewal Payment rows are money and
    # stay (the FK to them lives on the term side); the leads queue goes with the module.
    terms, term_labels = _delete(
        MembershipTerm.objects.filter(membership__makerspace=makerspace)
    )
    plans, plan_labels = _delete(MembershipPlan.objects.filter(makerspace=makerspace))
    leads, lead_labels = _delete(InvitationRequest.objects.filter(makerspace=makerspace))
    return _counts(
        model_labels=(
            profile_labels | request_labels | card_labels | term_labels | plan_labels
            | lead_labels
        ),
        member_cards=cards,
        member_profiles=profiles,
        membership_requests=requests,
        membership_terms=terms,
        membership_plans=plans,
        invitation_requests=leads,
    )
