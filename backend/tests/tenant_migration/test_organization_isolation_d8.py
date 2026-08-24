from datetime import timedelta
import uuid

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.events.models import Event, EventOrganizer
from apps.events.organizer_authority import can_manage_event
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.organizations.models import (
    Organization,
    OrganizationMakerspace,
    OrganizationMembership,
)
from apps.tenant_migration.tenant_dump_source_projection import project_makerspace_source


pytestmark = pytest.mark.django_db


def test_lane_d_drops_all_organization_authority_and_real_event_path_is_inert():
    space = Makerspace.objects.create(
        name="D8 organization source", slug="d8-organization-source"
    )
    actor = User.objects.create_user(
        username="d8-organization-actor", access_status=User.AccessStatus.ACTIVE
    )
    inert_role = MakerspaceRole.objects.create(
        makerspace=space, name="D8 ordinary member", slug="d8-ordinary-member",
        granted_actions=[],
    )
    MakerspaceMembership.objects.create(
        makerspace=space, user=actor, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=inert_role,
    )
    organization = Organization.objects.create(
        name="Source organization", slug="d8-source-organization"
    )
    OrganizationMakerspace.objects.create(
        organization=organization,
        makerspace=space,
        relationship=OrganizationMakerspace.Relationship.MANAGER,
    )
    OrganizationMembership.objects.create(
        organization=organization,
        user=actor,
        granted_actions=[Action.MANAGE_EVENTS],
    )
    starts = timezone.now() + timedelta(days=1)
    event = Event.objects.create(
        makerspace=space,
        title="Source organization event",
        starts_at=starts,
        ends_at=starts + timedelta(hours=1),
    )
    EventOrganizer.objects.create(event=event, organization=organization)
    assert can_manage_event(actor, event) is True

    projection = project_makerspace_source(
        space.pk, capture_id=uuid.uuid4()
    )

    assert "organizations.Organization" not in projection.rows
    assert "organizations.OrganizationMakerspace" not in projection.rows
    assert "organizations.OrganizationMembership" not in projection.rows
    assert "events.EventOrganizer" not in projection.rows

    organization.delete()
    event.refresh_from_db()
    assert EventOrganizer.objects.filter(event=event).exists() is False
    assert can_manage_event(actor, event) is False
