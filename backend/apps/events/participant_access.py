"""Membership history stays protected; account tickets authorize only their own row."""

from django.shortcuts import get_object_or_404

from apps.events.models import EventRegistration
from apps.makerspaces.member_activity_service import active_membership
from apps.makerspaces.guards import require_module
from apps.presence.guard import require_active_account


def participant_space(user, makerspace_id, registration_id):
    membership = active_membership(user, makerspace_id)
    if membership is not None:
        return membership.makerspace
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
