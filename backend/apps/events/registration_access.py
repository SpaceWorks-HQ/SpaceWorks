"""Audience checks shared by every registration caller."""

from rest_framework.exceptions import ValidationError

from apps.makerspaces.platform import feature_enabled, module_enabled
from apps.makerspaces.models import MakerspaceMembership
from apps.presence.guard import require_active_account, require_active_member, MemberPresenceRequired


def validate_event_audience(event):
    from rest_framework.exceptions import NotFound
    from .models_categories import EventCategory
    category_id = getattr(event, "category_id", None)
    if category_id and not EventCategory.objects.filter(pk=category_id, makerspace=event.makerspace).exists():
        raise NotFound("Category not found.")
    key = {"accounts": "events.account_registration", "invite": "events.invites"}.get(event.registration_audience)
    if key and not feature_enabled(event.makerspace, key):
        raise ValidationError({"registration_audience": "Enable this event audience feature first."})


def require_registration_access(event, member, *, staff=False, collaborative=False, via=None):
    # Keep the trusted legacy service seam for old imports/tests using contact-only
    # registrations. HTTP callers always supply an identified account.
    if member is None:
        if event.registration_audience != "members":
            raise MemberPresenceRequired()
        return
    validate_event_audience(event)
    if collaborative:
        require_active_member(member, via or event.makerspace)
    elif event.registration_audience == "members":
        if not module_enabled(event.makerspace, "membership"):
            raise MemberPresenceRequired()
        if staff:
            require_active_account(member, event.makerspace)
            if not MakerspaceMembership.objects.filter(user=member, makerspace=event.makerspace, status="active").exists():
                raise MemberPresenceRequired()
        else:
            require_active_member(member, event.makerspace)
    else:
        require_active_account(member, event.makerspace)


def has_active_event_membership(user, makerspace):
    return bool(
        module_enabled(makerspace, "membership")
        and user and user.is_authenticated and user.is_active
        and user.access_status == "active"
        and MakerspaceMembership.objects.filter(user=user, makerspace=makerspace, status="active").exists()
    )
