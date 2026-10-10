import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.boxes.models import QrCode
from apps.inventory.models import InventoryAsset, TrackingMode
from apps.operations.models import QrPrintBatch, StockTransfer, StocktakeSession
from tests.return_helpers import make_product, make_space, make_user
from tests.accounts.mfa_helpers import force_mfa_login

pytestmark = pytest.mark.django_db


def make_superadmin(username="ops-admin-actions-super"):
    return make_user(
        username,
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )


def admin_client(user=None):
    client = Client()
    force_mfa_login(client, user or make_superadmin())
    return client


def post_admin_action(client, url, action, obj):
    return client.post(
        url,
        {
            "action": action,
            ACTION_CHECKBOX_NAME: [str(obj.pk)],
            "index": "0",
        },
    )


def test_stocktake_admin_complete_and_approve_actions_transition_status():
    user = make_superadmin("ops-stocktake-action-super")
    makerspace = make_space("ops-stocktake-actions")
    stocktake = StocktakeSession.objects.create(makerspace=makerspace, started_by=user)
    url = reverse("admin:operations_stocktakesession_changelist")
    client = admin_client(user)

    complete_response = post_admin_action(client, url, "complete_selected", stocktake)
    stocktake.refresh_from_db()
    approve_response = post_admin_action(client, url, "approve_selected", stocktake)
    stocktake.refresh_from_db()

    assert complete_response.status_code == 302
    assert approve_response.status_code == 302
    assert stocktake.status == StocktakeSession.Status.APPROVED
    assert stocktake.completed_at is not None
    assert stocktake.approved_by == user
    assert stocktake.approved_at is not None


def test_stock_transfer_admin_add_is_enabled_for_custom_service_flow():
    client = admin_client(make_superadmin("ops-transfer-admin-super"))

    response = client.get(reverse("admin:operations_stocktransfer_add"))

    assert response.status_code == 200
    assert b"Create stock transfer" in response.content


def test_generate_qr_assets_admin_action_creates_assets_and_qr_codes():
    makerspace = make_space("ops-qr-assets-action")
    product = make_product(
        makerspace,
        name="Router",
        tracking_mode=TrackingMode.QUANTITY,
        total_quantity=0,
        available_quantity=0,
    )
    client = admin_client(make_superadmin("ops-qr-assets-super"))

    response = client.post(
        reverse("admin:inventory_inventoryproduct_changelist"),
        {
            "action": "generate_qr_assets",
            ACTION_CHECKBOX_NAME: [str(product.pk)],
            "index": "0",
            "apply": "1",
            "count": "3",
        },
    )

    assert response.status_code == 302
    assert InventoryAsset.objects.filter(product=product).count() == 3
    assert QrCode.objects.filter(
        makerspace=makerspace,
        target_type=QrCode.TargetType.ASSET,
        target_id__in=InventoryAsset.objects.filter(product=product).values("id"),
    ).count() == 3
    product.refresh_from_db()
    assert product.tracking_mode == TrackingMode.INDIVIDUAL


def test_mark_printed_admin_action_sets_batch_printed():
    user = make_superadmin("ops-print-batch-super")
    makerspace = make_space("ops-print-batch-action")
    batch = QrPrintBatch.objects.create(makerspace=makerspace, title="Labels", created_by=user)
    client = admin_client(user)

    response = post_admin_action(
        client,
        reverse("admin:operations_qrprintbatch_changelist"),
        "mark_printed_selected",
        batch,
    )
    batch.refresh_from_db()

    assert response.status_code == 302
    assert batch.status == QrPrintBatch.Status.PRINTED
    assert batch.printed_at is not None
