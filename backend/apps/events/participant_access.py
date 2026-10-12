"""Membership history stays protected; account tickets authorize only their own row."""

from django.shortcuts import get_object_or_404

from apps.events.models import EventRegistration
from apps.makerspaces.member_activity_service import active_membership
from apps.makerspaces.guards import require_module
from apps.presence.guard import MemberPresenceRequired, require_active_account
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.servability import servable_queryset


def participant_space(user, makerspace_id, registration_id):
    space = get_object_or_404(servable_queryset(Makerspace.objects.all()), pk=makerspace_id)
    require_active_account(user, space)
    membership = active_membership(user, makerspace_id)
    if membership is not None:
        return membership.makerspace
    if MakerspaceMembership.objects.filter(user=user, makerspace=space).exists():
        # A revoked membership cannot fall back to account-only ticket authority.
        raise MemberPresenceRequired()
    registration = get_object_or_404(
        EventRegistration.objects.select_related("event__makerspace").filter(
            member=user, event__makerspace_id=makerspace_id,
            registration_audience__in=("accounts", "invite"),
        ), pk=registration_id,
    )
    space = registration.event.makerspace
    require_module(space, "events")
    require_active_account(user, space)
    return space
