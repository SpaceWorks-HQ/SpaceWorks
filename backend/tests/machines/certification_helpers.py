"""Shared fixtures for the certification-gating tests.

Split out so `test_certifications.py` (the gate) and `test_certifications_api.py` (the
staff surfaces) stay inside the file-size ceiling while building identical worlds.
"""

from datetime import timedelta
from uuid import uuid4

from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.bookings.models import BookableSpace
from apps.bookings.services_bookings import create_booking
from apps.machines import service_workflow_actions as service_workflow
from apps.machines.models import CertificationType, MachineType, RoleMachineTypeScope
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from tests.return_helpers import make_user


def _space(slug, *, modules=("machines", "machine_service", "bookings"), certifications=True):
    space = Makerspace.objects.create(name=slug, slug=slug)
    space.enabled_modules = sorted(set(space.enabled_modules) | set(modules))
    space.enabled_features = sorted(
        set(space.enabled_features or [])
        | ({"machines.certifications"} if certifications else set())
    )
    space.save(update_fields=["enabled_modules", "enabled_features"])
    return space


def _member(space, username):
    """A plain member: a custom role granting nothing, so no authority masks the gate."""
    user = make_user(username, access_status=User.AccessStatus.ACTIVE)
    # Member bookings copy the contact phone from the account, and the booking model
    # requires one.
    user.phone = "123"
    user.save(update_fields=["phone"])
    role = MakerspaceRole.objects.create(
        makerspace=space, name=f"{username}-member", slug=f"{username}-member",
        granted_actions=[],
    )
    membership = MakerspaceMembership.objects.create(
        user=user,
        makerspace=space,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    return user, membership


def _manager(space, username, machine_type=None, actions=(Action.MANAGE_MACHINES,)):
    """A custom-role actor holding MANAGE_MACHINES, optionally linked to one type."""
    user = make_user(username, access_status=User.AccessStatus.ACTIVE)
    role = MakerspaceRole.objects.create(
        makerspace=space, name=username, slug=username, granted_actions=list(actions)
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=space,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    if machine_type is not None:
        RoleMachineTypeScope.objects.create(role=role, machine_type=machine_type)
    return user, role


def _machine_type(space, label="Laser"):
    return MachineType.objects.create(
        makerspace=space, slug=f"cert-{uuid4().hex[:8]}", name=label
    )


def _certification(space, machine_type, **kwargs):
    return CertificationType.objects.create(
        makerspace=space,
        machine_type=machine_type,
        name=kwargs.pop("name", "Laser induction"),
        is_required_for_service=kwargs.pop("is_required_for_service", True),
        is_required_for_booking=kwargs.pop("is_required_for_booking", True),
        **kwargs,
    )


def _bookable(space, machine_type=None):
    return BookableSpace.objects.create(
        makerspace=space,
        name="Laser bench",
        machine_type=machine_type,
        approval_mode=BookableSpace.ApprovalMode.INSTANT,
    )


def _book(space_row, member, **kwargs):
    start = timezone.now() + timedelta(days=1)
    return create_booking(
        space_row, starts_at=start, ends_at=start + timedelta(hours=1),
        member=member, **kwargs
    )


def _submit(machine, member, **kwargs):
    return service_workflow.submit(
        machine, member, member=member, actor=member,
        requester_name="Member", contact_email="member@example.test",
        contact_phone="123", title="Cut this", **kwargs
    )


