from types import SimpleNamespace

from apps.boxes.models import QrCode, QrScanEvent
from apps.hardware_requests.models import (
    HardwareRequestItem,
    HardwareRequestItemAsset,
    PublicToolLoan,
)
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.models import MembershipRequest
from apps.operations.models import (
    InventoryAdjustment,
    StockTransfer,
    StockTransferLine,
)
from tests.data_export.portable_helpers import make_space


def create_row_closure_scenario(space, actor, request):
    local_product = InventoryProduct.objects.create(
        makerspace=space,
        name="Closure drill",
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1,
        available_quantity=1,
    )
    present_asset = InventoryAsset.objects.create(
        makerspace=space,
        product=local_product,
        asset_tag="STAYS-HERE",
    )
    foreign = make_space(f"{space.slug}-asset-destination")
    foreign_product = InventoryProduct.objects.create(
        makerspace=foreign,
        name="Transferred drill",
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1,
        available_quantity=1,
    )
    moved_asset = InventoryAsset.objects.create(
        makerspace=foreign,
        product=foreign_product,
        asset_tag="MOVED-AWAY",
    )

    request_item = HardwareRequestItem.objects.create(
        request=request,
        product=local_product,
        requested_quantity=2,
        accepted_quantity=2,
        issued_quantity=2,
    )
    present_link = HardwareRequestItemAsset.objects.create(
        request_item=request_item,
        asset=present_asset,
    )
    moved_link = HardwareRequestItemAsset.objects.create(
        request_item=request_item,
        asset=moved_asset,
    )

    moved_adjustment = InventoryAdjustment.objects.create(
        makerspace=space,
        asset=moved_asset,
        delta_available=-1,
        reason="Moved asset history",
        created_by=actor,
    )
    blank_adjustment = InventoryAdjustment.objects.create(
        makerspace=space,
        delta_available=1,
        reason="Originally no asset",
        created_by=actor,
    )

    present_qr = QrCode.objects.create(
        makerspace=space,
        target_type=QrCode.TargetType.ASSET,
        target_id=present_asset.pk,
        created_by=actor,
    )
    rebound_qr = QrCode.objects.create(
        makerspace=space,
        target_type=QrCode.TargetType.ASSET,
        target_id=moved_asset.pk,
        created_by=actor,
    )
    rebound_scan = QrScanEvent.objects.create(
        makerspace=space,
        qr_code=rebound_qr,
        request=request,
        actor=actor,
        context=QrScanEvent.Context.ISSUE,
    )
    loan = PublicToolLoan.objects.create(
        makerspace=space,
        qr_code=present_qr,
        request=request,
        requester=actor,
        target_type="asset",
        target_id=present_asset.pk,
        target_label=present_asset.asset_tag,
        asset_ids=[present_asset.pk, moved_asset.pk],
        qr_ids=[present_qr.pk, rebound_qr.pk],
        status=PublicToolLoan.Status.RETURNED,
    )

    inbound_transfer = StockTransfer.objects.create(
        makerspace=foreign,
        source_makerspace=foreign,
        destination_makerspace=space,
        created_by=actor,
        reason="Inbound from another owner",
    )
    inbound_line = StockTransferLine.objects.create(
        transfer=inbound_transfer,
        product=foreign_product,
        quantity=1,
        notes="Foreign-owned line",
    )
    inbound_adjustment = InventoryAdjustment.objects.create(
        makerspace=space,
        transfer=inbound_transfer,
        product=local_product,
        delta_available=1,
        reason="Inbound adjustment",
        created_by=actor,
    )

    open_invitation = MembershipRequest.objects.create(
        makerspace=space,
        invite_email="unapproved-target-member@example.test",
        kind=MembershipRequest.Kind.INVITE,
        state=MembershipRequest.State.INVITED,
        invited_by=actor,
        assigned_role=space.roles.get(slug="member"),
        auto_activate_on_claim=True,
    )
    terminal_request = MembershipRequest.objects.create(
        makerspace=space,
        user=actor,
        kind=MembershipRequest.Kind.REQUEST,
        state=MembershipRequest.State.ACTIVE,
        requested_by=actor,
        assigned_role=space.roles.get(slug="member"),
    )
    return SimpleNamespace(**locals())
