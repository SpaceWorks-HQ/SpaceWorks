from apps.accounts import rbac
from apps.boxes.models import Box, QrCode
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.platform import feature_enabled, module_enabled


def _allowed_scanner_actions(user, qr):
    actions = ["view"]
    if module_enabled(qr.makerspace, "scanner") and rbac.can(
        user,
        rbac.Action.MANAGE_QR,
        qr.makerspace_id,
    ):
        actions.append("record_scan")
    if qr.target_type in {QrCode.TargetType.PRODUCT, QrCode.TargetType.ASSET, QrCode.TargetType.BOX}:
        if feature_enabled(qr.makerspace, "inventory.self_checkout"):
            from apps.hardware_requests.self_checkout_workflow import qr_has_active_loan

            if qr_has_active_loan(qr.makerspace, qr):
                actions.append("return")
            elif _qr_checkout_eligible(qr, require_public=True):
                actions.append("checkout")
        if (
            feature_enabled(qr.makerspace, "inventory.self_checkout")
            and rbac.can(user, rbac.Action.ISSUE_DIRECT_LOAN, qr.makerspace_id)
            and _qr_checkout_eligible(qr, require_public=False)
        ):
            actions.append("direct_handout")
    if qr.target_type == QrCode.TargetType.BOX:
        actions.append("contents")
        if rbac.can(user, rbac.Action.MANAGE_QR, qr.makerspace_id):
            actions.append("move_container")
    if rbac.can(user, rbac.Action.MANAGE_QR, qr.makerspace_id):
        actions.append("revoke")
    return sorted(set(actions))


def _qr_checkout_eligible(qr, *, require_public):
    if qr.target_type == QrCode.TargetType.PRODUCT:
        product = InventoryProduct.objects.filter(pk=qr.target_id, makerspace=qr.makerspace).first()
        return _product_checkout_eligible(product, require_public=require_public)
    if qr.target_type == QrCode.TargetType.ASSET:
        asset = (
            InventoryAsset.objects.select_related("product")
            .filter(pk=qr.target_id, makerspace=qr.makerspace)
            .first()
        )
        return _asset_checkout_eligible(asset, require_public=require_public)
    if qr.target_type == QrCode.TargetType.BOX:
        return _box_checkout_eligible(qr, require_public=require_public)
    return False


def _product_checkout_eligible(product, *, require_public):
    if product is None or product.is_archived or product.available_quantity < 1:
        return False
    if product.tracking_mode == TrackingMode.INDIVIDUAL:
        return False
    if require_public and (not product.is_public or not product.public_self_checkout_enabled):
        return False
    return True


def _asset_checkout_eligible(asset, *, require_public):
    if asset is None or asset.status != InventoryAsset.Status.AVAILABLE:
        return False
    product = asset.product
    if product is None or product.is_archived or product.available_quantity < 1:
        return False
    if require_public and (
        not asset.public_self_checkout_enabled
        or not product.is_public
        or not product.public_self_checkout_enabled
    ):
        return False
    return True


def _box_checkout_eligible(qr, *, require_public):
    from apps.hardware_requests.models import PublicToolLoan

    box = Box.objects.filter(pk=qr.target_id, makerspace=qr.makerspace).first()
    if box is None or not box.is_active:
        return False
    if PublicToolLoan.objects.filter(
        makerspace=qr.makerspace,
        container=box,
        status=PublicToolLoan.Status.CHECKED_OUT,
    ).exists():
        return False
    asset_filters = {
        "box": box,
        "status": InventoryAsset.Status.AVAILABLE,
        "product__is_archived": False,
        "product__available_quantity__gte": 1,
    }
    product_filters = {
        "box": box,
        "is_archived": False,
        "available_quantity__gte": 1,
    }
    if require_public:
        asset_filters.update(
            {
                "public_self_checkout_enabled": True,
                "product__is_public": True,
                "product__public_self_checkout_enabled": True,
            }
        )
        product_filters.update(
            {"is_public": True, "public_self_checkout_enabled": True}
        )
    if InventoryAsset.objects.filter(**asset_filters).exists():
        return True
    products = InventoryProduct.objects.filter(**product_filters)
    if products.filter(tracking_mode=TrackingMode.INDIVIDUAL).exists():
        return False
    return products.exists()
