import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.hardware_requests.models import (
    HardwareRequest,
    HardwareRequestItem,
    PublicProblemReport,
    PublicToolLoan,
    RequesterAccountability,
)
from apps.inventory.models import InventoryAsset, TrackingMode
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import authenticated_client, make_member, make_product, make_space, make_user
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def _triage_url(makerspace, report):
    return f"/api/v1/admin/makerspace/{makerspace.id}/problem-reports/{report.id}/triage"


def _returned_report(makerspace, product, requester=None, *, quantity=1, asset_ids=None):
    requester = requester or make_user(f"problem-requester-{makerspace.slug}", access_status=User.AccessStatus.ACTIVE)
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.RETURNED,
        issued_at=timezone.now(),
        closed_at=timezone.now(),
    )
    item = HardwareRequestItem.objects.create(
        request=request,
        product=product,
        requested_quantity=quantity,
        accepted_quantity=quantity,
        issued_quantity=quantity,
        returned_quantity=quantity,
    )
    loan = PublicToolLoan.objects.create(
        makerspace=makerspace,
        request=request,
        requester=requester,
        target_type="product",
        target_id=product.id,
        target_label=product.name,
        asset_ids=asset_ids or [],
        status=PublicToolLoan.Status.RETURNED,
        returned_at=timezone.now(),
    )
    report = PublicProblemReport.objects.create(
        makerspace=makerspace,
        loan=loan,
        request=request,
        requester=requester,
        note="Reported during public return.",
    )
    return report, item


def _payload(outcome, item, quantity=1):
    return {
        "outcome": outcome,
        "resolutions": [{"item_id": item.id, "quantity": quantity}],
        "note": "Confirmed by staff.",
    }


def test_damaged_triage_moves_quantity_stock_available_to_damaged():
    makerspace = make_space("problem-damaged")
    manager = make_member("problem-damaged-manager", makerspace)
    product = make_product(makerspace, total_quantity=1, available_quantity=1, damaged_quantity=0)
    report, item = _returned_report(makerspace, product)

    response = authenticated_client(manager).post(_triage_url(makerspace, report), _payload("damaged", item), format="json")

    assert response.status_code == 200
    product.refresh_from_db()
    report.refresh_from_db()
    assert product.available_quantity == 0
    assert product.damaged_quantity == 1
    assert product.total_quantity == 1
    assert report.outcome == PublicProblemReport.Outcome.DAMAGED
    assert report.resolved_by == manager


def test_needs_fix_triage_moves_quantity_stock_to_needs_fix_shelf():
    makerspace = make_space("problem-needs-fix")
    manager = make_member("problem-needs-fix-manager", makerspace)
    product = make_product(makerspace, total_quantity=1, available_quantity=1, needs_fix_quantity=0)
    report, item = _returned_report(makerspace, product)

    response = authenticated_client(manager).post(_triage_url(makerspace, report), _payload("needs_fix", item), format="json")

    assert response.status_code == 200
    product.refresh_from_db()
    assert product.available_quantity == 0
    assert product.needs_fix_quantity == 1
    assert product.total_quantity == 1


def test_missing_triage_moves_quantity_stock_to_lost_and_creates_accountability():
    makerspace = make_space("problem-missing")
    manager = make_member("problem-missing-manager", makerspace)
    product = make_product(makerspace, total_quantity=1, available_quantity=1, lost_quantity=0)
    requester = make_user("problem-missing-requester", access_status=User.AccessStatus.ACTIVE)
    report, item = _returned_report(makerspace, product, requester=requester)

    response = authenticated_client(manager).post(_triage_url(makerspace, report), _payload("missing", item), format="json")

    assert response.status_code == 200
    product.refresh_from_db()
    assert product.available_quantity == 0
    assert product.lost_quantity == 1
    accountability = RequesterAccountability.objects.get()
    assert accountability.requester == requester
    assert accountability.request_item == item
    assert accountability.issue_type == RequesterAccountability.IssueType.MISSING
    assert accountability.quantity == 1
    assert accountability.description == "Confirmed by staff."


def test_no_issue_triage_moves_no_stock_and_creates_no_accountability():
    makerspace = make_space("problem-no-issue")
    manager = make_member("problem-no-issue-manager", makerspace)
    product = make_product(makerspace, total_quantity=1, available_quantity=1)
    report, _item = _returned_report(makerspace, product)

    response = authenticated_client(manager).post(
        _triage_url(makerspace, report),
        {"outcome": "no_issue", "resolutions": [], "note": "Looks fine."},
        format="json",
    )

    assert response.status_code == 200
    product.refresh_from_db()
    report.refresh_from_db()
    assert product.available_quantity == 1
    assert product.damaged_quantity == 0
    assert product.lost_quantity == 0
    assert product.needs_fix_quantity == 0
    assert not RequesterAccountability.objects.exists()
    assert report.outcome == PublicProblemReport.Outcome.NO_ISSUE
    assert report.triage_note == "Looks fine."


def test_retriaging_resolved_report_is_rejected_without_double_movement():
    makerspace = make_space("problem-idempotent")
    manager = make_member("problem-idempotent-manager", makerspace)
    product = make_product(makerspace, total_quantity=1, available_quantity=1, damaged_quantity=0)
    report, item = _returned_report(makerspace, product)
    client = authenticated_client(manager)

    first = client.post(_triage_url(makerspace, report), _payload("damaged", item), format="json")
    second = client.post(_triage_url(makerspace, report), {"outcome": "no_issue"}, format="json")

    assert first.status_code == 200
    assert second.status_code == 409
    product.refresh_from_db()
    assert product.available_quantity == 0
    assert product.damaged_quantity == 1
    assert RequesterAccountability.objects.count() == 1


def test_triage_over_issued_quantity_is_rejected_with_clean_400():
    makerspace = make_space("problem-overage")
    manager = make_member("problem-overage-manager", makerspace)
    product = make_product(makerspace, total_quantity=1, available_quantity=1)
    report, item = _returned_report(makerspace, product)

    response = authenticated_client(manager).post(_triage_url(makerspace, report), _payload("damaged", item, quantity=2), format="json")

    assert response.status_code == 400
    product.refresh_from_db()
    assert product.available_quantity == 1
    assert product.damaged_quantity == 0
    assert not RequesterAccountability.objects.exists()


def test_triage_rbac_wrong_role_403_and_cross_tenant_404():
    makerspace = make_space("problem-rbac")
    other = make_space("problem-rbac-other")
    guest = make_handout_member("problem-rbac-guest", makerspace)
    other_manager = make_member("problem-rbac-other-manager", other)
    product = make_product(makerspace, total_quantity=1, available_quantity=1)
    report, item = _returned_report(makerspace, product)

    wrong_role = authenticated_client(guest).post(_triage_url(makerspace, report), _payload("damaged", item), format="json")
    cross_tenant = authenticated_client(other_manager).post(_triage_url(makerspace, report), _payload("damaged", item), format="json")

    assert wrong_role.status_code == 403
    assert cross_tenant.status_code == 404


@pytest.mark.parametrize(
    ("outcome", "target_status"),
    [("damaged", InventoryAsset.Status.DAMAGED), ("needs_fix", InventoryAsset.Status.MAINTENANCE)],
)
def test_individual_tracked_triage_flips_returned_asset_status(outcome, target_status):
    makerspace = make_space(f"problem-asset-{outcome}")
    manager = make_member(f"problem-asset-{outcome}-manager", makerspace)
    product = make_product(
        makerspace,
        total_quantity=1,
        available_quantity=1,
        tracking_mode=TrackingMode.INDIVIDUAL,
    )
    asset = InventoryAsset.objects.create(
        makerspace=makerspace,
        product=product,
        asset_tag=f"ASSET-{outcome}",
        status=InventoryAsset.Status.AVAILABLE,
    )
    report, item = _returned_report(makerspace, product, asset_ids=[asset.id])

    response = authenticated_client(manager).post(_triage_url(makerspace, report), _payload(outcome, item), format="json")

    assert response.status_code == 200
    asset.refresh_from_db()
    product.refresh_from_db()
    assert asset.status == target_status
    assert product.available_quantity == 0
    if outcome == "needs_fix":
        assert product.needs_fix_quantity == 1
    else:
        assert product.damaged_quantity == 1