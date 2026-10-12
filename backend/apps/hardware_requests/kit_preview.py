"""Read-only target lookup for checklist capture, never issues stock."""

from collections import Counter

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.accounts import rbac
from apps.boxes.access import inventory_qr_codes
from apps.boxes.models import Box, QrCode
from apps.hardware_requests.kit_checklists import expectations, unique_expectations
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.platform import feature_enabled


def preview_targets(actor, makerspace, *, items=(), qr_payloads=(), container_id=None, public=False):
    action = rbac.Action.ISSUE_DIRECT_LOAN
    def scoped(rows):
        return (rbac.scope_by_makerspace(actor, rows) if public else
                rbac.scope_by_action(actor, action, rows)).filter(makerspace=makerspace)

    quantities = Counter()
    box = get_object_or_404(scoped(Box.objects.all()), pk=container_id, is_active=True) if container_id else None
    products = scoped(InventoryProduct.objects.filter(is_archived=False))
    assets = scoped(InventoryAsset.objects.filter(status=InventoryAsset.Status.AVAILABLE, product__is_archived=False))
    if public:
        products = products.filter(is_public=True, public_self_checkout_enabled=True)
        assets = assets.filter(public_self_checkout_enabled=True, product__is_public=True,
                               product__public_self_checkout_enabled=True)
    for entry in items:
        product = get_object_or_404(products, pk=entry["product_id"])
        quantities[product] += entry["quantity"]
    seen = set()
    for payload in qr_payloads:
        if payload in seen:
            raise ValidationError("The same QR was scanned more than once.")
        seen.add(payload)
        qr = get_object_or_404(scoped(inventory_qr_codes(QrCode.objects.all())),
                               payload=payload, status=QrCode.Status.ACTIVE)
        if qr.target_type == QrCode.TargetType.PRODUCT:
            quantities[get_object_or_404(products, pk=qr.target_id)] += 1
        elif qr.target_type == QrCode.TargetType.ASSET:
            asset = get_object_or_404(assets.select_related("product"), pk=qr.target_id)
            quantities[asset.product] += 1
        else:
            target = get_object_or_404(scoped(Box.objects.all()), pk=qr.target_id, is_active=True)
            if box and box.pk != target.pk:
                raise ValidationError("Only one container may be checked out.")
            box = target
            for asset in assets.filter(box=box).select_related("product"):
                quantities[asset.product] += 1
            for product in products.filter(box=box, tracking_mode=TrackingMode.QUANTITY, available_quantity__gt=0):
                quantities[product] += 1
    if not feature_enabled(makerspace, "loans.kit_checklist"):
        return []
    groups = [(f"product:{product.pk}", expectations(product.kit_components, product.name, count))
              for product, count in quantities.items()]
    if box:
        groups.append((f"box:{box.pk}", expectations(box.kit_components, box.label)))
    return [row for _owner, rows in unique_expectations(groups) for row in rows]
