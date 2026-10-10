import uuid
from urllib.parse import urlsplit

import pytest
from django.conf import settings
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.boxes.models import QrCode
from apps.evidence.models import EvidencePhoto
from apps.inventory.models import InventoryAsset
from apps.operations.models import QrPrintBatch
from tests.return_helpers import make_product, make_space, make_user
from tests.accounts.mfa_helpers import force_mfa_login

pytestmark = pytest.mark.django_db


def make_superadmin(username="admin-monitoring-super"):
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


def csp_directive(response, directive):
    csp = response["Content-Security-Policy"]
    for section in csp.split(";"):
        parts = section.strip().split()
        if parts and parts[0] == directive:
            return parts[1:]
    return []


def s3_public_origin_or_skip():
    endpoint = getattr(settings, "AWS_S3_PUBLIC_ENDPOINT_URL", "") or ""
    if not endpoint:
        pytest.skip("AWS_S3_PUBLIC_ENDPOINT_URL is blank")
    parts = urlsplit(endpoint)
    if not parts.scheme or not parts.netloc:
        pytest.skip("AWS_S3_PUBLIC_ENDPOINT_URL does not include an origin")
    return f"{parts.scheme}://{parts.netloc}"


def test_qr_print_batch_download_zip_action_streams_one_selected_batch():
    user = make_superadmin("admin-monitoring-zip-one")
    makerspace = make_space("admin-monitoring-zip-one")
    batch = QrPrintBatch.objects.create(
        makerspace=makerspace,
        title="Empty batch",
        created_by=user,
    )
    client = admin_client(user)

    response = post_admin_action(
        client,
        reverse("admin:operations_qrprintbatch_changelist"),
        "download_zip_selected",
        batch,
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert f"qr-batch-{batch.pk}.zip" in response["Content-Disposition"]


def test_qr_print_batch_download_zip_action_redirects_for_two_selected_batches():
    user = make_superadmin("admin-monitoring-zip-two")
    makerspace = make_space("admin-monitoring-zip-two")
    first_batch = QrPrintBatch.objects.create(
        makerspace=makerspace,
        title="First batch",
        created_by=user,
    )
    second_batch = QrPrintBatch.objects.create(
        makerspace=makerspace,
        title="Second batch",
        created_by=user,
    )
    client = admin_client(user)

    response = client.post(
        reverse("admin:operations_qrprintbatch_changelist"),
        {
            "action": "download_zip_selected",
            ACTION_CHECKBOX_NAME: [str(first_batch.pk), str(second_batch.pk)],
            "index": "0",
        },
    )

    assert response.status_code == 302
    assert response.get("Content-Type") != "application/zip"


def test_control_login_csp_img_src_allows_s3_public_origin():
    origin = s3_public_origin_or_skip()
    client = Client()

    response = client.get("/control/login/", SERVER_NAME="localhost")

    assert response.status_code == 200
    assert origin in csp_directive(response, "img-src")


def test_global_csp_img_src_does_not_allow_s3_public_origin():
    origin = s3_public_origin_or_skip()
    client = Client()

    response = client.get("/", SERVER_NAME="localhost")

    assert response.status_code == 200
    assert origin not in csp_directive(response, "img-src")


def test_qr_code_change_page_renders_for_superadmin():
    user = make_superadmin("admin-monitoring-qr-code")
    makerspace = make_space("admin-monitoring-qr-code")
    product = make_product(makerspace, name="QR render item")
    qr_code = QrCode.objects.create(
        makerspace=makerspace,
        payload=f"qr-{uuid.uuid4().hex}",
        target_type=QrCode.TargetType.PRODUCT,
        target_id=product.pk,
        status=QrCode.Status.ACTIVE,
        created_by=user,
    )

    response = admin_client(user).get(
        reverse("admin:boxes_qrcode_change", args=[qr_code.pk])
    )

    assert response.status_code == 200


def test_inventory_asset_change_page_renders_without_active_qr():
    user = make_superadmin("admin-monitoring-asset")
    makerspace = make_space("admin-monitoring-asset")
    product = make_product(makerspace, name="Asset render item")
    asset = InventoryAsset.objects.create(
        makerspace=makerspace,
        product=product,
        asset_tag="ASSET-RENDER-1",
    )

    response = admin_client(user).get(
        reverse("admin:inventory_inventoryasset_change", args=[asset.pk])
    )

    assert response.status_code == 200


def test_evidence_photo_change_page_renders_with_object_key():
    user = make_superadmin("admin-monitoring-evidence")
    makerspace = make_space("admin-monitoring-evidence")
    evidence = EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=EvidencePhoto.EvidenceType.RETURN,
        object_key=f"evidence/{makerspace.id}/return/{uuid.uuid4().hex}.jpg",
        uploaded_by=user,
    )

    response = admin_client(user).get(
        reverse("admin:evidence_evidencephoto_change", args=[evidence.pk])
    )

    assert response.status_code == 200
