"""Staff waiver and plan/term API paths the audit found untested (00-audit.md §5, §7).

The waiver publish endpoint had no API test at all; it supersedes, refuses a reused version,
clears, audits, and is core (works with the module off). Plan and term APIs are the
module's own surface and answer 400 at every verb with it off.
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.makerspaces import waiver_services
from apps.makerspaces.models import MakerspaceMembership, MakerspaceWaiver, MembershipPlan
from apps.makerspaces.membership_plan_services import create_term
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db(transaction=True)


def _waiver_url(makerspace):
    return reverse("admin-makerspace-waiver", args=[makerspace.pk])


def test_publishing_a_waiver_supersedes_refuses_a_reused_version_and_audits():
    makerspace = space("waiver-api")
    client = authenticated_client(manager(makerspace, "waiver-api-manager"))

    first = client.put(_waiver_url(makerspace), {"body": "Be careful.", "version": "v1"}, format="json")
    second = client.put(_waiver_url(makerspace), {"body": "Be more careful.", "version": "v2"}, format="json")
    reused = client.put(_waiver_url(makerspace), {"body": "Again.", "version": "v1"}, format="json")

    assert (first.status_code, second.status_code, reused.status_code) == (200, 200, 400)
    v1, v2 = (MakerspaceWaiver.objects.get(makerspace=makerspace, version=v) for v in ("v1", "v2"))
    assert (v1.is_active, v2.is_active) == (False, True)
    assert v1.superseded_at is not None and v2.superseded_at is None
    assert AuditLog.objects.filter(action="makerspace.waiver_published", makerspace=makerspace).count() == 2


def test_clearing_the_waiver_deactivates_it_and_audits():
    makerspace = space("waiver-clear")
    client = authenticated_client(manager(makerspace, "waiver-clear-manager"))
    client.put(_waiver_url(makerspace), {"body": "Be careful.", "version": "v1"}, format="json")

    response = client.put(_waiver_url(makerspace), {"clear": True}, format="json")

    assert response.status_code == 200 and response.data == {"has_waiver": False}
    assert not MakerspaceWaiver.objects.filter(makerspace=makerspace, is_active=True).exists()
    assert AuditLog.objects.filter(action="makerspace.waiver_deactivated", makerspace=makerspace).exists()


def test_waiver_publishing_and_witnessing_are_core_with_the_module_off():
    makerspace = space("waiver-core")
    boss = manager(makerspace, "waiver-core-manager")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=user("waiver-core-member"),
        assigned_role=member_role(makerspace), role="custom",
    )
    disable_module(makerspace, "membership")
    client = authenticated_client(boss)

    assert client.put(_waiver_url(makerspace), {"body": "Be careful.", "version": "v1"}, format="json").status_code == 200
    witnessed = client.post(
        reverse("admin-membership-waiver-witness", args=[membership.pk]), {}, format="json",
    )
    assert witnessed.status_code == 200, witnessed.data


def test_witnessing_with_no_active_waiver_is_refused():
    makerspace = space("waiver-none")
    boss = manager(makerspace, "waiver-none-manager")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=user("waiver-none-member"),
        assigned_role=member_role(makerspace), role="custom",
    )

    with pytest.raises(ValidationError, match="no active waiver"):
        waiver_services.witness_waiver_acceptance(boss, membership.pk)


def test_plan_create_and_update_are_audited():
    makerspace = space("plan-audit")
    client = authenticated_client(manager(makerspace, "plan-audit-manager"))

    created = client.post(
        reverse("admin-membership-plans", args=[makerspace.pk]),
        {"name": "Monthly", "interval": "monthly", "amount": "10.00"}, format="json",
    )
    client.patch(reverse("admin-membership-plan-detail", args=[created.data["id"]]), {"is_active": False}, format="json")

    assert MembershipPlan.objects.get(pk=created.data["id"]).is_active is False
    actions = set(AuditLog.objects.filter(makerspace=makerspace).values_list("action", flat=True))
    assert {"membership_plan.created", "membership_plan.updated"} <= actions


def test_every_plan_and_term_verb_answers_400_with_the_module_off():
    makerspace = space("plan-module-off")
    boss = manager(makerspace, "plan-module-off-manager")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=user("plan-module-off-member"),
        assigned_role=member_role(makerspace), role="custom",
    )
    plan = MembershipPlan.objects.create(makerspace=makerspace, name="Monthly", interval="monthly", amount=Decimal("5"))
    term = create_term(boss, membership, plan)
    disable_module(makerspace, "membership")
    client = authenticated_client(boss)

    responses = [
        client.post(reverse("admin-membership-plans", args=[makerspace.pk]), {"name": "X", "interval": "monthly", "amount": "1"}, format="json"),
        client.patch(reverse("admin-membership-plan-detail", args=[plan.pk]), {"amount": "6"}, format="json"),
        client.get(reverse("admin-membership-terms", args=[membership.pk])),
        client.post(reverse("admin-membership-terms", args=[membership.pk]), {"plan_id": plan.pk}, format="json"),
        client.post(reverse("admin-membership-term-cancel", args=[term.pk])),
    ]

    assert [response.status_code for response in responses] == [400] * 5
    term.refresh_from_db()
    assert term.status == "active"
    assert AuditLog.objects.filter(action="membership.term_cancelled", makerspace=makerspace).count() == 0
