from types import SimpleNamespace

from django.db import transaction

from apps.hardware_requests import workflow
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.inventory import availability
from tests.return_helpers import (
    make_box, make_issue_evidence, make_member, make_product, make_space,
    make_user, make_return_evidence,
)

PRODUCT_KEY = "3dfc785b-405a-489a-8a18-de84254ed930"
BOX_KEY = "23622e7c-6c32-46e1-a2b7-8b390bf45ab7"


def kit_setup(slug="kits", *, quantity=1, product_kit=True, box_kit=False):
    space = make_space(slug)
    space.enabled_features = [*space.enabled_features, "loans.kit_checklist"]
    space.save(update_fields=["enabled_features"])
    actor = make_member(f"staff-{slug}", space)
    borrower = make_user(f"borrower-{slug}")
    product = make_product(space, kit_components=[
        {"key": PRODUCT_KEY, "label": "Driver bits", "quantity": 12},
    ] if product_kit else [])
    box = make_box(space)
    if box_kit:
        box.kit_components = [{"key": BOX_KEY, "label": "Carry strap", "quantity": 1}]
        box.save(update_fields=["kit_components"])
    request = HardwareRequest.objects.create(makerspace=space, requester=borrower,
        requester_username=borrower.username, status=HardwareRequest.Status.ACCEPTED)
    item = HardwareRequestItem.objects.create(request=request, product=product,
        requested_quantity=quantity, accepted_quantity=quantity)
    with transaction.atomic():
        availability.reserve_for_request(request)
    return SimpleNamespace(space=space, actor=actor, borrower=borrower, product=product,
                           box=box, request=request, item=item, quantity=quantity)


def issue_kit(data, *, product_present=None, box_present=1):
    data.request = workflow.assign_box(data.actor, data.request, data.box.code)
    counts = []
    if data.product.kit_components:
        counts.append({"key": PRODUCT_KEY, "present": product_present if product_present is not None else 12 * data.quantity})
    if data.box.kit_components:
        counts.append({"key": BOX_KEY, "present": box_present})
    data.request = workflow.issue_request(data.actor, data.request,
        make_issue_evidence(data.space, data.actor).pk, kit_checklist=counts)
    return data.request


def return_kit(data, counts, *, quantity=None, remark="Returned and inspected."):
    return workflow.return_items(data.actor, data.request,
        make_return_evidence(data.space, data.actor).pk, remark, data.box.code,
        [{"item_id": data.item.pk, "returned": quantity or data.quantity, "damaged": 0, "missing": 0}],
        kit_checklist=counts)
