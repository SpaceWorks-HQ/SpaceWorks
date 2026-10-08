"""Shared actors and spaces for the phase-10 audit explorer tests."""

from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import User
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.organizations.models import (
    Organization,
    OrganizationMakerspace,
    OrganizationMembership,
)


def user(username, **kwargs):
    kwargs.setdefault("access_status", User.AccessStatus.ACTIVE)
    return User.objects.create_user(username=username, password="pw-strong-123", **kwargs)


def space(slug):
    return Makerspace.objects.create(name=slug.title(), slug=slug)


def superadmin(username="audit-root"):
    return user(username, role=User.Role.SUPERADMIN, is_superuser=True, is_staff=True)


def member_with(makerspace, username, legacy_role):
    actor = user(username)
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=makerspace,
        role=legacy_role,
        assigned_role=MakerspaceRole.objects.get(makerspace=makerspace, legacy_role=legacy_role),
    )
    return actor


def custom_role_member(makerspace, username, actions):
    actor = user(username)
    role = MakerspaceRole.objects.create(
        makerspace=makerspace,
        name=f"{username} role",
        slug=f"{username}-role",
        granted_actions=sorted(actions),
    )
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    return actor


def org_auditor(makerspace, username):
    organization = Organization.objects.create(name=f"{username} org", slug=f"{username}-org")
    OrganizationMakerspace.objects.create(
        organization=organization,
        makerspace=makerspace,
        relationship=OrganizationMakerspace.Relationship.OWNER,
    )
    actor = user(username)
    OrganizationMembership.objects.create(
        organization=organization, user=actor, granted_actions=[rbac.Action.VIEW_AUDIT]
    )
    return actor


def client_for(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client
