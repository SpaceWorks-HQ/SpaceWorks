from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.boxes.models import Box
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership

pytestmark = pytest.mark.django_db


def make_user(username, role=User.Role.REQUESTER, **kw):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@e.com",
        role=role,
        **kw,
    )


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_inventory_manager(username, makerspace):
    user = make_user(
        username,
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    return user


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def make_product(makerspace):
    return InventoryProduct.objects.create(
        makerspace=makerspace,
        name="Oscilloscope",
        description="Bench scope",
        total_quantity=2,
        available_quantity=2,
        reserved_quantity=0,
        is_public=True,
    )


def make_accepted_request(makerspace, product):
    requester = make_user(
        "inventory-manager-requester",
        access_status=User.AccessStatus.ACTIVE,
    )
    hardware_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.ACCEPTED,
    )
    HardwareRequestItem.objects.create(
        request=hardware_request,
        product=product,
        requested_quantity=1,
        accepted_quantity=1,
    )
    product.available_quantity -= 1
    product.reserved_quantity += 1
    product.save(update_fields=["available_quantity", "reserved_quantity", "updated_at"])
    return hardware_request


def upload_url(makerspace):
    return f"/api/v1/admin/makerspaces/{makerspace.id}/uploads/evidence-url"


def test_inventory_manager_requester_can_assign_issue_upload_evidence_and_return(
    monkeypatch,
):
    makerspace = make_space("inventory-manager-lifecycle")
    inventory_manager = make_inventory_manager("inventory-manager-user", makerspace)
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product)
    box = Box.objects.create(makerspace=makerspace, label="Return Bin")
    client = authenticated_client(inventory_manager)
    monkeypatch.setattr(
        "apps.evidence.services_upload.presigned_upload",
        lambda object_key, content_type: {
            "url": "http://minio/evidence",
            "fields": {"key": object_key, "Content-Type": content_type},
        },
    )
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))
    monkeypatch.setattr(
        "apps.hardware_requests.notifications.notify_request_issued",
        Mock(),
    )
    monkeypatch.setattr(
        "apps.hardware_requests.notifications.notify_request_returned",
        Mock(),
    )

    issue_upload = client.post(
        upload_url(makerspace),
        {"evidence_type": "issue", "content_type": "image/png"},
        format="json",
    )
    assigned = client.post(
        f"/api/v1/admin/requests/{hardware_request.id}/assign-box",
        {"box_code": box.code},
        format="json",
    )
    issued = client.post(
        f"/api/v1/admin/requests/{hardware_request.id}/issue",
        {
            "evidence_id": issue_upload.data["evidence_id"],
            "remark": "Issued by inventory manager.",
        },
        format="json",
    )
    return_upload = client.post(
        upload_url(makerspace),
        {"evidence_type": "return", "content_type": "image/png"},
        format="json",
    )
    hardware_request.refresh_from_db()
    item = hardware_request.items.get()
    returned = client.post(
        f"/api/v1/admin/requests/{hardware_request.id}/return",
        {
            "evidence_id": return_upload.data["evidence_id"],
            "box_code": box.code,
            "remark": "Returned by inventory manager.",
            "resolutions": [
                {
                    "item_id": item.id,
                    "returned": 1,
                    "damaged": 0,
                    "missing": 0,
                }
            ],
        },
        format="json",
    )

    assert issue_upload.status_code == 201
    assert assigned.status_code == 200
    assert issued.status_code == 200
    assert return_upload.status_code == 201
    assert returned.status_code == 200
    inventory_manager.refresh_from_db()
    assert inventory_manager.role == User.Role.REQUESTER
    assert EvidencePhoto.objects.filter(uploaded_by=inventory_manager).count() == 2
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.RETURNED
    assert hardware_request.issued_by == inventory_manager
    assert hardware_request.closed_by == inventory_manager
