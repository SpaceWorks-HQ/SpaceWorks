import uuid

from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.boxes.models import Box, BoxScan
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership


def make_user(username, role=User.Role.REQUESTER, **kw):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@e.com",
        role=role,
        **kw,
    )


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def enable_online_rail(makerspace, domain):
    """Switch the ONLINE rail on for one domain, alongside charge tracking.

    Charge tracking (`charges.*`) decides whether a debt is recorded; the payments
    feature set decides whether a Stripe/Razorpay rail may be raised for it. A test that
    exercises checkout, a payment intent, or provider provenance needs both, because the
    member-facing checkout and mobile-intent endpoints now refuse to mint a provider
    object for a charge whose space has no live rail.
    """
    features = set(makerspace.enabled_features or [])
    features |= {
        "payments.enabled",
        f"payments.{domain}",
        "charges.enabled",
        f"charges.{domain}",
    }
    makerspace.enabled_features = sorted(features)
    makerspace.save(update_fields=["enabled_features", "updated_at"])
    return makerspace


def settlement_payload(**overrides):
    """The receipt body every mark-offline endpoint now requires.

    A charge marked paid offline must be able to say how and when the money arrived, so
    method and received_at are mandatory at the API boundary.
    """
    from django.utils import timezone

    payload = {"method": "cash", "reference": "", "received_at": timezone.now().isoformat()}
    payload.update(overrides)
    return {"settlement": payload}


def make_member(
    username,
    makerspace,
    membership_role=MakerspaceMembership.Role.SPACE_MANAGER,
    role=User.Role.SPACE_MANAGER,
):
    user = make_user(username, role=role, access_status=User.AccessStatus.ACTIVE)
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=membership_role,
    )
    return user


def make_print_manager(username, makerspace):
    return make_member(
        username,
        makerspace,
        membership_role=MakerspaceMembership.Role.MACHINE_MANAGER,
        role=User.Role.REQUESTER,
    )


def make_product(makerspace, name="Oscilloscope", **overrides):
    defaults = {
        "makerspace": makerspace,
        "name": name,
        "description": f"{name} description",
        "total_quantity": 10,
        "available_quantity": 10,
        "reserved_quantity": 0,
        "issued_quantity": 0,
        "damaged_quantity": 0,
        "lost_quantity": 0,
        "is_public": True,
        "is_archived": False,
    }
    defaults.update(overrides)
    return InventoryProduct.objects.create(**defaults)


def make_box(makerspace, label=None):
    return Box.objects.create(
        makerspace=makerspace,
        label=label or f"B-{uuid.uuid4().hex[:8]}",
    )


def make_return_evidence(makerspace, actor):
    return EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=EvidencePhoto.EvidenceType.RETURN,
        object_key=f"evidence/{makerspace.id}/return/{uuid.uuid4().hex}",
        uploaded_by=actor,
    )


def make_issue_evidence(makerspace, actor):
    return EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=f"evidence/{makerspace.id}/issue/{uuid.uuid4().hex}",
        uploaded_by=actor,
    )


def make_issued_request(makerspace, actor, product_quantities):
    requester = make_user(
        f"requester-{makerspace.slug}-{uuid.uuid4().hex[:8]}",
        access_status=User.AccessStatus.ACTIVE,
    )
    box = make_box(makerspace)
    hardware_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.ISSUED,
        assigned_box=box,
        issued_by=actor,
    )
    for product, quantity in product_quantities:
        product.available_quantity -= quantity
        product.issued_quantity += quantity
        product.save(
            update_fields=["available_quantity", "issued_quantity", "updated_at"]
        )
        HardwareRequestItem.objects.create(
            request=hardware_request,
            product=product,
            requested_quantity=quantity,
            accepted_quantity=quantity,
            issued_quantity=quantity,
        )
    BoxScan.objects.create(
        makerspace=makerspace,
        box=box,
        request=hardware_request,
        actor=actor,
        context=BoxScan.Context.ISSUE,
    )
    return hardware_request


def make_accepted_request(makerspace, product, quantity):
    requester = make_user(
        f"accepted-requester-{makerspace.slug}-{uuid.uuid4().hex[:8]}",
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
        requested_quantity=quantity,
        accepted_quantity=quantity,
    )
    return hardware_request


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def return_url(hardware_request):
    return f"/api/v1/admin/requests/{hardware_request.id}/return"


def active_loans_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/active-loans"


def return_payload(hardware_request, evidence, *, box_code=None, remark="All checked."):
    return {
        "evidence_id": evidence.id,
        "box_code": box_code or hardware_request.assigned_box.code,
        "remark": remark,
        "resolutions": [
            {
                "item_id": item.id,
                "returned": item.issued_quantity
                - item.returned_quantity
                - item.damaged_quantity
                - item.missing_quantity,
                "damaged": 0,
                "missing": 0,
            }
            for item in hardware_request.items.order_by("id")
        ],
    }
