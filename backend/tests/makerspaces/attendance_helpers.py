"""Shared fixtures for the attended-events profile tests.

Extracted so the consent tests and the payload-contract tests can live in separate
modules under the 300-line ceiling without either one duplicating setup.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.events.models import Event, EventRegistration
from apps.makerspaces import profile_services
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole


def make_space(slug="attended-space"):
    return Makerspace.objects.create(name=slug, slug=slug)


def member(makerspace, username="attended-member", display_name="Ada Lovelace"):
    user = User.objects.create_user(
        username=f"{username}-{makerspace.slug}",
        email=f"{username}-{makerspace.slug}@example.test",
        display_name=display_name,
        access_status=User.AccessStatus.ACTIVE,
    )
    return MakerspaceMembership.objects.create(
        user=user, makerspace=makerspace, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=makerspace, slug="member"),
        status="active",
    )


def authed(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def profile_url(makerspace):
    return f"/api/v1/member/makerspaces/{makerspace.id}/profile"


def directory_url(makerspace):
    return f"/api/v1/member/makerspaces/{makerspace.id}/directory"


def disable_events(makerspace):
    makerspace.enabled_modules = [
        key for key in makerspace.enabled_modules if key != "events"
    ]
    makerspace.save(update_fields=["enabled_modules"])
    return makerspace


def attend(membership, title, *, days_ago=1, status=EventRegistration.Status.ATTENDED,
           linked=True):
    start = timezone.now() - timedelta(days=days_ago)
    event = Event.objects.create(
        makerspace=membership.makerspace, title=title,
        starts_at=start, ends_at=start + timedelta(hours=2),
        is_public=True, status=Event.Status.COMPLETED,
    )
    user = membership.user
    return EventRegistration.objects.create(
        event=event,
        member=user if linked else None,
        name=user.display_name,
        email=user.email if linked else "someone-else@example.test",
        phone="1234567890",
        status=status,
    )


def publish(membership, *, attended=True):
    profile_services.save_profile(
        membership, {"is_visible": True, "show_attended_events": attended}
    )
