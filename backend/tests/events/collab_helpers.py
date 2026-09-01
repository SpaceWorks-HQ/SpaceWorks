"""Shared fixtures for the collaborative-events tests."""

from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.events.models import Event, EventCollaborator
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
)


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_staff(space, username=None):
    user = User.objects.create_user(
        username=f"{username or 'staff'}-{space.slug}",
        email=f"{username or 'staff'}-{space.slug}@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user, makerspace=space, role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return user


def make_member(space, username="member", user=None):
    """Create a member, or give an EXISTING user a membership in a second space.

    The `user` form matters for cross-tenant tests: `make_member` derives its username from
    the space, so calling it twice makes two different people, and a test using two accounts
    is stopped by the membership check without ever exercising the scoping it claims to test.
    """
    if user is None:
        user = User.objects.create_user(
            username=f"{username}-{space.slug}",
            email=f"{username}-{space.slug}@example.test",
            display_name=username,
            phone="1234567890",
            access_status=User.AccessStatus.ACTIVE,
        )
    MakerspaceMembership.objects.create(
        user=user, makerspace=space, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
        status="active",
    )
    return user


def make_event(space, *, is_public=False, status=Event.Status.PUBLISHED, title="Joint build"):
    start = timezone.now() + timedelta(hours=1)
    return Event.objects.create(
        makerspace=space, title=title, status=status, is_public=is_public,
        starts_at=start, ends_at=start + timedelta(hours=3),
    )


def collaborate(event, space, status=EventCollaborator.Status.ACCEPTED):
    return EventCollaborator.objects.create(event=event, makerspace=space, status=status)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client
