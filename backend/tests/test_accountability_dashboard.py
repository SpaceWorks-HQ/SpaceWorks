from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.hardware_requests.models import (
    HardwareRequest,
    HardwareRequestItem,
    PublicToolLoan,
    RequesterAccountability,
)
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import authenticated_client, make_member, make_product, make_space, make_user
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def _url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/accountability"


def _request_with_item(makerspace, product, requester, *, status=HardwareRequest.Status.ISSUED, due_at=None):
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=status,
        issued_at=timezone.now() - timedelta(days=4),
        return_due_at=due_at,
    )
    item = HardwareRequestItem.objects.create(
        request=request,
        product=product,
        requested_quantity=2,
        accepted_quantity=2,
        issued_quantity=2,
    )
    return request, item


def _accountability(makerspace, requester, request, item, issue_type, quantity, actor):
    return RequesterAccountability.objects.create(
        makerspace=makerspace,
        requester=requester,
        request=request,
        request_item=item,
        issue_type=issue_type,
        quantity=quantity,
        created_by=actor,
    )


def _direct_loan(makerspace, product, requester, *, due_at):
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.ISSUED,
        issued_at=timezone.now() - timedelta(days=3),
        return_due_at=due_at,
    )
    return PublicToolLoan.objects.create(
        makerspace=makerspace,
        request=request,
        requester=requester,
        target_type="product",
        target_id=product.id,
        target_label=product.name,
        status=PublicToolLoan.Status.CHECKED_OUT,
        due_at=due_at,
    )


def test_accountability_dashboard_aggregates_repeat_offenders_overdue_and_restrictions():
    makerspace = make_space("accountability-dashboard")
    manager = make_member("accountability-manager", makerspace)
    requester = make_user(
        "accountability-repeat",
        access_status=User.AccessStatus.RESTRICTED,
        restriction_reason="Lost tools pending review.",
    )
    other_requester = make_user("accountability-on-time", access_status=User.AccessStatus.ACTIVE)
    product = make_product(makerspace, name="Thermal Camera")
    past_due = timezone.now() - timedelta(days=2)
    future_due = timezone.now() + timedelta(days=2)
    request, item = _request_with_item(makerspace, product, requester, due_at=past_due)
    _accountability(
        makerspace,
        requester,
        request,
        item,
        RequesterAccountability.IssueType.DAMAGED,
        1,
        manager,
    )
    _accountability(
        makerspace,
        requester,
        request,
        item,
        RequesterAccountability.IssueType.MISSING,
        2,
        manager,
    )
    overdue_direct = _direct_loan(makerspace, product, requester, due_at=past_due)
    _direct_loan(makerspace, product, other_requester, due_at=future_due)

    response = authenticated_client(manager).get(_url(makerspace))

    assert response.status_code == 200
    assert response.data["repeat_offenders"] == [
        {
            "requester_id": requester.id,
            "username": requester.username,
            "access_status": User.AccessStatus.RESTRICTED,
            "restriction_reason": "Lost tools pending review.",
            "damaged": 1,
            "missing": 1,
            "total_issues": 2,
            "total_quantity": 3,
        }
    ]
    overdue = {(row["type"], row["reference_id"]): row for row in response.data["overdue"]}
    assert ("request", request.id) in overdue
    assert ("direct", overdue_direct.id) in overdue
    assert len(response.data["overdue"]) == 2
    assert all(row["requester_username"] != other_requester.username for row in response.data["overdue"])
    assert overdue[("request", request.id)]["label"] == "Thermal Camera"
    assert overdue[("direct", overdue_direct.id)]["label"] == "Thermal Camera"
    assert overdue[("request", request.id)]["days_overdue"] >= 2
    assert response.data["restrictions"] == [
        {
            "requester_id": requester.id,
            "username": requester.username,
            "access_status": User.AccessStatus.RESTRICTED,
            "restriction_reason": "Lost tools pending review.",
        }
    ]
    assert response.data["truncated"] == {"repeat_offenders": False, "overdue": False, "problem_reports": False}


def test_accountability_dashboard_cross_tenant_makerspace_returns_404():
    space_a = make_space("accountability-scope-a")
    space_b = make_space("accountability-scope-b")
    manager_a = make_member("accountability-scope-manager-a", space_a)

    response = authenticated_client(manager_a).get(_url(space_b))

    assert response.status_code == 404


def test_accountability_dashboard_requires_view_audit_in_same_makerspace():
    makerspace = make_space("accountability-view-audit")
    guest = make_handout_member("accountability-guest-admin", makerspace)

    response = authenticated_client(guest).get(_url(makerspace))

    assert response.status_code == 403


def test_accountability_surfaces_and_resolves_public_problem_reports():
    from apps.hardware_requests.models import PublicProblemReport

    makerspace = make_space("accountability-problems")
    admin = make_member("accountability-problems-admin", makerspace)
    product = make_product(makerspace, total_quantity=2, available_quantity=2)
    requester = make_user("problem-reporter")
    loan = _direct_loan(makerspace, product, requester, due_at=timezone.now() + timedelta(days=3))
    report = PublicProblemReport.objects.create(
        makerspace=makerspace,
        loan=loan,
        request=loan.request,
        requester=requester,
        note="Tip is bent.",
    )

    client = authenticated_client(admin)
    response = client.get(_url(makerspace))
    assert response.status_code == 200
    assert [row["id"] for row in response.data["problem_reports"]] == [report.id]
    assert response.data["problem_reports"][0]["note"] == "Tip is bent."

    resolve = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/problem-reports/{report.id}/resolve",
        {},
        format="json",
    )
    assert resolve.status_code == 200
    report.refresh_from_db()
    assert report.resolved_at is not None
    assert report.resolved_by == admin

    after = client.get(_url(makerspace))
    assert after.data["problem_reports"] == []
