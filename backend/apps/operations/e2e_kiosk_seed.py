"""Isolated real-workflow kiosk fixtures; secrets go only in the seed JSON file."""

from types import SimpleNamespace

from apps.audit import services as audit
from apps.boxes.models import Box, QrCode
from apps.hardware_requests import workflow
from apps.inventory import availability
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.kiosk_station_services import create_station


def seed_kiosk(makerspace, manager, member, token):
    makerspace.enabled_features = sorted(set(makerspace.enabled_features) | {"inventory.kiosk"})
    makerspace.save(update_fields=["enabled_features", "updated_at"])
    audit.record(manager, "makerspace.features_updated", makerspace=makerspace, target=makerspace,
                 meta={"enabled_features": makerspace.enabled_features})
    station, credential, pin = create_station(makerspace, actor=manager, name="E2E offline handover", kind="handover")
    cases = []
    for name, individual in (("offline-success", False), ("offline-revoked", True)):
        box = Box.objects.create(makerspace=makerspace, label=f"E2E {name} {token}")
        product = InventoryProduct.objects.create(
            makerspace=makerspace, name=f"E2E {name} tool {token}", box=box,
            tracking_mode=TrackingMode.INDIVIDUAL if individual else TrackingMode.QUANTITY,
            total_quantity=1, available_quantity=1, is_public=False,
        )
        qr = None
        if individual:
            asset = InventoryAsset.objects.create(makerspace=makerspace, product=product, box=box,
                                                  asset_tag=f"e2e-offline-{token}")
            availability.reconcile_individual_product_from_assets(product)
            qr = QrCode.objects.create(makerspace=makerspace, target_type=QrCode.TargetType.ASSET, target_id=asset.pk)
        row = workflow.submit_request(
            makerspace, [{"product": product, "quantity": 1}], f"E2E {name}",
            requester_principal=member, audit_actor=member,
            contact_snapshot=SimpleNamespace(username=member.username, name="E2E Member", email=member.email,
                                             phone="", contact_verified=True),
        )
        workflow.accept_request(manager, row)
        if individual:
            # The failure scenario queues only issue, so the required box scan exists.
            workflow.assign_box(manager, row, box.code)
        cases.append({"request_id": row.pk, "box_code": box.code, "qr_id": qr.pk if qr else None,
                      "qr_payload": qr.payload if qr else None})
    return {"station_token": str(credential.public_token), "station_pin": pin,
            "station_id": station.pk, "success": cases[0], "revoked": cases[1]}
