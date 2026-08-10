"""Shared fixtures for the QR check-in tests, split across two modules."""

from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.events.models import Event, EventRegistration
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
)


def make_space(slug="checkin-space"):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_staff(space, username="checkin-staff"):
    user = User.objects.create_user(
        username=f"{username}-{space.slug}",
        email=f"{username}-{space.slug}@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user, makerspace=space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return user


def make_member(space, username="checkin-member", display_name="Ada Lovelace"):
    user = User.objects.create_user(
        username=f"{username}-{space.slug}",
        email=f"{username}-{space.slug}@example.test",
        display_name=display_name,
        phone="1234567890",
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user, makerspace=space, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
        status="active",
    )
    return user


def add_membership(space, user):
    """Give an EXISTING user an active membership in a second space.

    Needed because `make_member` derives its username from the space, so calling it twice
    makes two different people -- and a cross-tenant test that accidentally uses two
    accounts is stopped by the membership check and never exercises the binding it claims
    to test.
    """
    return MakerspaceMembership.objects.create(
        user=user, makerspace=space, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
        status="active",
    )


def make_event(space, title="Workshop", status=Event.Status.PUBLISHED, **values):
    start = values.pop("starts_at", timezone.now() + timedelta(hours=1))
    return Event.objects.create(
        makerspace=space, title=title, status=status,
        starts_at=start, ends_at=values.pop("ends_at", start + timedelta(hours=2)),
        is_public=values.pop("is_public", True), **values
    )


def register(event, user=None, *, status=EventRegistration.Status.REGISTERED,
             email="guest@example.test"):
    return EventRegistration.objects.create(
        event=event,
        member=user,
        name=user.display_name if user else "Guest",
        email=user.email if user else email,
        phone="1234567890",
        status=status,
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client
