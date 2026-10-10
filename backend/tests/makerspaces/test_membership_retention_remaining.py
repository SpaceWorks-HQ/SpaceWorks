"""Membership purge, report module composition, archive discovery and editions."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.makerspaces import membership_services, waiver_services
from apps.makerspaces.models import InvitationRequest, MakerspaceMembership, MembershipPlan, MembershipTerm
from apps.makerspaces.module_purge import purge_module
from apps.makerspaces.reports_community import build_community_engagement
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db(transaction=True)


def test_membership_purge_removes_terms_plans_and_leads_but_keeps_membership_and_waiver():
    makerspace, other = space("retention-purge"), space("retention-purge-other")
    boss = manager(makerspace, "retention-purge-manager")
    row = MakerspaceMembership.objects.create(makerspace=makerspace, user=user("retention-purge-member"), assigned_role=member_role(makerspace), role="custom")
    waiver = waiver_services.publish_waiver(boss, makerspace, "Terms", "v1")
    waiver_services.accept_waiver(row)
    plan = MembershipPlan.objects.create(makerspace=makerspace, name="Monthly", interval="monthly", amount="0")
    foreign_plan = MembershipPlan.objects.create(makerspace=other, name="Foreign", interval="monthly", amount="0")
    now = timezone.now()
    term = MembershipTerm.objects.create(membership=row, plan=plan, starts_at=now, ends_at=now + timedelta(days=30))
    lead = InvitationRequest.objects.create(makerspace=makerspace, name="Visitor", email="purge-visitor@example.test")
    disable_module(makerspace, "membership")
    superadmin = User.objects.create_superuser(username="retention-purge-admin", email="purge-admin@example.test", password="password")
    counts = purge_module(makerspace, "membership", superadmin)
    assert not MembershipTerm.objects.filter(pk=term.pk).exists()
    assert not MembershipPlan.objects.filter(pk=plan.pk).exists()
    assert not InvitationRequest.objects.filter(pk=lead.pk).exists()
    assert MembershipPlan.objects.filter(pk=foreign_plan.pk).exists()
    row.refresh_from_db()
    assert row.status == "active" and row.accepted_waiver_id == waiver.pk
    assert counts["membership_terms"] == counts["membership_plans"] == counts["invitation_requests"] == 1


def test_community_report_hides_membership_metrics_module_off_without_hiding_other_sections():
    makerspace = space("community-report-membership")
    MakerspaceMembership.objects.create(makerspace=makerspace, user=user("community-report-member"), assigned_role=member_role(makerspace), role="custom", activated_at=timezone.now())
    enabled = {row["module_key"]: row for row in build_community_engagement(makerspace.pk).records}
    assert enabled["membership"]["active_accounts"] == enabled["membership"]["activations"] == 1
    disable_module(makerspace, "membership")
    disabled = {row["module_key"]: row for row in build_community_engagement(makerspace.pk).records}
    assert disabled["membership"]["enabled"] is False
    assert disabled["membership"]["active_accounts"] == disabled["membership"]["activations"] == 0
    assert disabled["member_accounts"]["active_accounts"] == 1


def test_archive_removes_memberships_and_invitations_from_discovery_over_http():
    makerspace = space("archive-membership-discovery")
    boss = manager(makerspace, "archive-discovery-manager")
    person = user("archive-discovery-member")
    MakerspaceMembership.objects.create(makerspace=makerspace, user=person, assigned_role=member_role(makerspace), role="custom")
    invitee = user("archive-discovery-invitee")
    membership_services.invite_membership(boss, makerspace, invitee.email, member_role(makerspace))
    member_client, invite_client = authenticated_client(person), authenticated_client(invitee)
    assert member_client.get(reverse("my-memberships")).data["memberships"]
    assert invite_client.get(reverse("membership-invitations")).data["invitations"]
    makerspace.archived_at = timezone.now(); makerspace.save(update_fields=["archived_at"])
    assert member_client.get(reverse("my-memberships")).data["memberships"] == []
    assert invite_client.get(reverse("membership-invitations")).data["invitations"] == []


@pytest.mark.parametrize("edition", ["makerspace", "events", "bookings", "organization"])
def test_membership_join_remains_available_in_every_edition(settings, edition):
    settings.SPACEWORKS_EDITION = edition
    makerspace = space(f"membership-edition-{edition}")
    person = user(f"membership-edition-{edition}-person")
    assert authenticated_client(person).post(reverse("public-membership-request", args=[makerspace.slug]), {}, format="json").status_code == 201
