from collections import Counter

from django.utils import timezone

from apps.boxes.access import inventory_qr_codes
from apps.boxes.models import Box, QrCode
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem, PublicToolLoan
from apps.hardware_requests.workflow_errors import RequestValidationError
from apps.inventory import availability
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode


def _locked_qr(makerspace, payload):
    # A member-card QR answers exactly like an unknown payload: it is an identity
    # credential, never a loanable target (see `boxes.access.inventory_qr_codes`).
    qr = (
        inventory_qr_codes(QrCode.objects.select_for_update())
        .filter(payload=payload, makerspace=makerspace, status=QrCode.Status.ACTIVE)
        .first()
    )
    if qr is None:
        raise RequestValidationError("QR code is not active for this makerspace.")
    return qr


def _checkout_target(qr, *, require_public=True):
    if qr.target_type == QrCode.TargetType.PRODUCT:
        product = _eligible_product(
            qr.target_id, qr.makerspace, require_public=require_public
        )
        if product.tracking_mode == TrackingMode.INDIVIDUAL:
            raise RequestValidationError(
                "Individual-tracked products require a scanned asset QR."
            )
        _issue_product(product, 1)
        return product.name, {product: 1}, [], None
    if qr.target_type == QrCode.TargetType.ASSET:
        asset = _eligible_asset(
            qr.target_id, qr.makerspace, require_public=require_public
        )
        _issue_product(asset.product, 1)
        asset.status = InventoryAsset.Status.ISSUED
        asset.save(update_fields=["status", "updated_at"])
        return asset.asset_tag, {asset.product: 1}, [asset.id], None
    if qr.target_type == QrCode.TargetType.BOX:
        return _checkout_box(qr, require_public=require_public)
    # Never fall through to the box branch: an unknown target's `target_id` is not a
    # Box pk, and reading it as one checks out an unrelated container.
    raise RequestValidationError("QR code is not active for this makerspace.")


def _checkout_box(qr, *, require_public=True):
    box = Box.objects.select_for_update().filter(pk=qr.target_id, makerspace=qr.makerspace).first()
    if box is None or not box.is_active:
        raise RequestValidationError("Box is not available for public self-checkout.")
    if PublicToolLoan.objects.filter(
        makerspace=qr.makerspace,
        container=box,
        status=PublicToolLoan.Status.CHECKED_OUT,
    ).exists():
        raise RequestValidationError("This box is already checked out.")
    asset_filters = {
        "box": box,
        "status": InventoryAsset.Status.AVAILABLE,
        "product__is_archived": False,
    }
    if require_public:
        asset_filters.update(
            {
                "public_self_checkout_enabled": True,
                "product__is_public": True,
                "product__public_self_checkout_enabled": True,
            }
        )
    assets = list(
        InventoryAsset.objects.select_for_update()
        .select_related("product")
        .filter(**asset_filters)
    )
    issued_quantities = Counter()
    issued_asset_ids = []
    if assets:
        # The assets were loaded with select_related("product") but that does NOT lock
        # the product rows. issue_available() requires the caller to hold a row lock, so
        # re-fetch the distinct products with select_for_update (in pk order to avoid
        # deadlocks) before mutating their quantity buckets.
        product_ids = {asset.product_id for asset in assets}
        locked_products = {
            product.pk: product
            for product in InventoryProduct.objects.select_for_update()
            .filter(pk__in=product_ids)
            .order_by("pk")
        }
        quantities = Counter(locked_products[asset.product_id] for asset in assets)
        for product, quantity in quantities.items():
            _issue_product(product, quantity)
        issued_asset_ids = [asset.id for asset in assets]
        InventoryAsset.objects.filter(pk__in=issued_asset_ids).update(
            status=InventoryAsset.Status.ISSUED
        )
        issued_quantities.update(quantities)

    product_filters = {
        "box": box,
        "is_archived": False,
        "available_quantity__gte": 1,
        # Individual assets were issued in the pass above. Remaining units may
        # live outside this container and must not enter the quantity-only pass.
        "tracking_mode": TrackingMode.QUANTITY,
    }
    if require_public:
        product_filters.update(
            {
                "is_public": True,
                "public_self_checkout_enabled": True,
            }
        )
    products = list(
        InventoryProduct.objects.select_for_update().filter(**product_filters).order_by("pk")
    )
    if not products:
        if issued_quantities:
            return box.label, dict(issued_quantities), issued_asset_ids, box
        raise RequestValidationError("Box has no public self-checkout items.")
    for product in products:
        _issue_product(product, 1)
        issued_quantities[product] += 1
    return box.label, dict(issued_quantities), issued_asset_ids, box


def _eligible_product(pk, makerspace, *, require_public=True):
    product = InventoryProduct.objects.select_for_update().filter(pk=pk, makerspace=makerspace).first()
    if product is None or product.is_archived:
        raise RequestValidationError("Tool is not enabled for public self-checkout.")
    if require_public and (
        not product.is_public or not product.public_self_checkout_enabled
    ):
        raise RequestValidationError("Tool is not enabled for public self-checkout.")
    return product


def _eligible_asset(pk, makerspace, *, require_public=True):
    asset = (
        InventoryAsset.objects.select_for_update()
        .select_related("product")
        .filter(pk=pk, makerspace=makerspace)
        .first()
    )
    if asset is None or asset.status != InventoryAsset.Status.AVAILABLE:
        raise RequestValidationError("Asset is not available for public self-checkout.")
    if require_public and not asset.public_self_checkout_enabled:
        raise RequestValidationError("Asset is not enabled for public self-checkout.")
    asset.product = _eligible_product(
        asset.product_id, makerspace, require_public=require_public
    )
    return asset


def _issue_product(product, quantity):
    # Friendly public-facing guard (-> 400) before delegating the actual count
    # mutation to the Inventory Availability module, which owns the math.
    if product.available_quantity < quantity:
        raise RequestValidationError("Tool is not currently available.")
    availability.issue_available(product, quantity)


def _issued_request(
    makerspace,
    requester,
    requester_username,
    product_quantities,
    *,
    requester_name="",
    contact_email="",
    contact_phone="",
    return_due_at=None,
    requested_for="Public QR self-checkout",
    issued_by=None,
):
    return _create_issued_request(
        makerspace,
        requester,
        requester_username,
        product_quantities,
        requester_name=requester_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        return_due_at=return_due_at,
        requested_for=requested_for,
        issued_by=issued_by or requester,
    )


def _create_issued_request(
    makerspace,
    requester,
    requester_username,
    product_quantities,
    *,
    requester_name="",
    contact_email="",
    contact_phone="",
    return_due_at=None,
    requested_for,
    issued_by,
):
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester_username,
        requester_name=requester_name.strip(),
        requester_contact_email=contact_email.strip(),
        requester_contact_phone=contact_phone.strip(),
        status=HardwareRequest.Status.ISSUED,
        requested_for=requested_for,
        issued_by=issued_by,
        issued_at=timezone.now(),
        return_due_at=return_due_at,
    )
    HardwareRequestItem.objects.bulk_create(
        [
            HardwareRequestItem(
                request=request,
                product=product,
                requested_quantity=quantity,
                accepted_quantity=quantity,
                issued_quantity=quantity,
            )
            for product, quantity in product_quantities.items()
        ]
    )
    return request


def _return_request_items(request):
    items = list(request.items.select_for_update())
    outstanding_items = [
        (item, item.issued_quantity - item.returned_quantity)
        for item in items
        if item.issued_quantity - item.returned_quantity > 0
    ]
    if not outstanding_items:
        return

    product_ids = {item.product_id for item, _outstanding in outstanding_items}
    locked_products = {
        product.pk: product
        for product in InventoryProduct.objects.select_for_update()
        .filter(pk__in=product_ids)
        .order_by("pk")
    }
    for item, outstanding in outstanding_items:
        product = locked_products[item.product_id]
        availability.return_to_available(product, outstanding)
        item.returned_quantity += outstanding
        item.save(update_fields=["returned_quantity"])
