from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.boxes.models import BoxScan, QrCode, QrScanEvent
from apps.hardware_requests.models import (
    HardwareRequest,
    HardwareRequestItem,
    HardwareRequestItemAsset,
    PublicProblemReport,
    PublicToolLoan,
    RequesterAccountability,
    ReturnEvent,
)
from apps.inventory.models import InventoryAsset, TrackingMode
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import (
    authenticated_client,
    make_box,
    make_issue_evidence,
    make_member,
    make_product,
    make_return_evidence,
    make_space,
    make_user,
)
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def _timeline_url(request):
    return f"/api/v1/admin/requests/{request.id}/timeline"


def _chain_url(product):
    return f"/api/v1/admin/inventory/{product.id}/chain-of-custody"


def _full_lifecycle_rows():
    base = timezone.now() - timedelta(days=2)
    makerspace = make_space("loan-timeline")
    manager = make_member("timeline-manager", makerspace)
    requester = make_user(
        "timeline-requester",
        access_status=User.AccessStatus.ACTIVE,
    )
    product = make_product(
        makerspace,
        name="Thermal Camera",
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=2,
        available_quantity=0,
        issued_quantity=0,
        damaged_quantity=1,
    )
    assets = [
        InventoryAsset.objects.create(makerspace=makerspace, product=product, asset_tag="TC-1", status=InventoryAsset.Status.AVAILABLE),
        InventoryAsset.objects.create(makerspace=makerspace, product=product, asset_tag="TC-2", status=InventoryAsset.Status.DAMAGED),
    ]
    qrs = [
        QrCode.objects.create(makerspace=makerspace, target_type=QrCode.TargetType.ASSET, target_id=assets[0].id, created_by=manager),
        QrCode.objects.create(makerspace=makerspace, target_type=QrCode.TargetType.ASSET, target_id=assets[1].id, created_by=manager),
    ]
    box = make_box(makerspace, "Timeline Box")
    issue_evidence = make_issue_evidence(makerspace, manager)
    return_evidence = make_return_evidence(makerspace, manager)
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        requester_name="Borrower Name",
        requester_contact_email="borrower@example.com",
        requester_contact_phone="555-1212",
        status=HardwareRequest.Status.CLOSED_WITH_ISSUE,
        accepted_by=manager,
        accepted_at=base + timedelta(seconds=10),
        assigned_box=box,
        issued_by=manager,
        issued_at=base + timedelta(seconds=30),
        issue_evidence=issue_evidence,
        issue_remark="Issued at desk.",
        closed_by=manager,
        closed_at=base + timedelta(seconds=70),
    )
    HardwareRequest.objects.filter(pk=request.pk).update(
        created_at=base,
        updated_at=base + timedelta(seconds=20),
    )
    request.refresh_from_db()
    item = HardwareRequestItem.objects.create(
        request=request,
        product=product,
        requested_quantity=2,
        accepted_quantity=2,
        issued_quantity=2,
        returned_quantity=1,
        damaged_quantity=1,
    )
    issue_scan = BoxScan.objects.create(makerspace=makerspace, box=box, request=request, actor=manager, context=BoxScan.Context.ISSUE)
    qr_issue = QrScanEvent.objects.create(makerspace=makerspace, qr_code=qrs[0], request=request, actor=manager, context=QrScanEvent.Context.ISSUE)
    return_event = ReturnEvent.objects.create(makerspace=makerspace, request=request, box=box, evidence=return_evidence, remark="Lens scratched.", actor=manager)
    qr_return = QrScanEvent.objects.create(makerspace=makerspace, qr_code=qrs[1], request=request, actor=manager, context=QrScanEvent.Context.RETURN)
    return_scan = BoxScan.objects.create(makerspace=makerspace, box=box, request=request, actor=manager, context=BoxScan.Context.RETURN)
    HardwareRequestItemAsset.objects.create(
        request_item=item,
        asset=assets[0],
        outcome=HardwareRequestItemAsset.Outcome.RETURNED,
        issued_at=timezone.now(),
        returned_at=timezone.now(),
        return_event=return_event,
    )
    HardwareRequestItemAsset.objects.create(
        request_item=item,
        asset=assets[1],
        outcome=HardwareRequestItemAsset.Outcome.DAMAGED,
        issued_at=timezone.now(),
        returned_at=timezone.now(),
        return_event=return_event,
    )
    accountability = RequesterAccountability.objects.create(
        makerspace=makerspace,
        requester=requester,
        request=request,
        request_item=item,
        issue_type=RequesterAccountability.IssueType.DAMAGED,
        quantity=1,
        evidence_photo=return_evidence,
        created_by=manager,
    )
    loan = PublicToolLoan.objects.create(
        makerspace=makerspace,
        request=request,
        requester=requester,
        target_type="direct",
        target_id=request.id,
        target_label=product.name,
        status=PublicToolLoan.Status.RETURNED,
        returned_at=base + timedelta(seconds=90),
    )
    report = PublicProblemReport.objects.create(makerspace=makerspace, loan=loan, request=request, requester=requester, note="Cable missing.")
    return makerspace, manager, requester, product, request


def test_request_timeline_orders_full_lifecycle_events():
    _, manager, _, _, request = _full_lifecycle_rows()

    response = authenticated_client(manager).get(_timeline_url(request))

    assert response.status_code == 200
    kinds = [event["kind"] for event in response.data["events"]]
    assert kinds[:6] == [
        "request_submitted",
        "request_accepted",
        "box_assigned",
        "issue_evidence",
        "box_scan",
        "qr_scan",
    ]
    assert "return_event" in kinds
    assert kinds.index("return_event") < kinds.index("accountability") < kinds.index("problem_report")
    assert response.data["events"][3]["evidence_id"] == request.issue_evidence_id
    assert all("object_key" not in event["detail"] for event in response.data["events"])


def test_chain_of_custody_groups_asset_outcomes():
    _, manager, _, product, _ = _full_lifecycle_rows()

    response = authenticated_client(manager).get(_chain_url(product))

    assert response.status_code == 200
    assert response.data["tracking_mode"] == TrackingMode.INDIVIDUAL
    outcomes_by_asset = {
        group["asset_tag"]: [event["detail"].get("outcome") for event in group["events"] if event["kind"] == "asset_outcome"]
        for group in response.data["asset_groups"]
    }
    assert outcomes_by_asset == {"TC-1": [HardwareRequestItemAsset.Outcome.RETURNED], "TC-2": [HardwareRequestItemAsset.Outcome.DAMAGED]}


def test_timeline_rbac_guest_gets_403_cross_tenant_gets_404():
    makerspace, _, _, _, request = _full_lifecycle_rows()
    other_space = make_space("loan-timeline-other")
    guest = make_handout_member("timeline-guest", makerspace)
    other_manager = make_member("timeline-other-manager", other_space)

    assert authenticated_client(guest).get(_timeline_url(request)).status_code == 403
    assert authenticated_client(other_manager).get(_timeline_url(request)).status_code == 404


def test_non_audit_role_receives_no_requester_pii():
    _, _, _, _, request = _full_lifecycle_rows()
    guest = make_handout_member("timeline-no-pii-guest", request.makerspace)

    response = authenticated_client(guest).get(_timeline_url(request))

    assert response.status_code == 403
    body = response.content.decode("utf-8")
    assert "borrower@example.com" not in body
    assert "555-1212" not in body
    assert "Borrower Name" not in body




