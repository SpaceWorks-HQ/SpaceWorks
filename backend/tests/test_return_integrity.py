from unittest.mock import Mock

import pytest
from django.db import transaction

from apps.hardware_requests.models import RequesterAccountability, ReturnEvent
from apps.inventory import availability
from apps.inventory.availability import InsufficientStock
from tests.return_helpers import (
    authenticated_client,
    make_issued_request,
    make_member,
    make_product,
    make_return_evidence,
    make_space,
    return_payload,
    return_url,
)

pytestmark = pytest.mark.django_db


def test_return_event_and_accountability_rows_are_immutable():
    makerspace = make_space("return-immutable")
    admin = make_member("return-immutable-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_issued_request(makerspace, admin, [(product, 1)])
    item = hardware_request.items.get()
    evidence = make_return_evidence(makerspace, admin)
    event = ReturnEvent.objects.create(
        request=hardware_request,
        makerspace=makerspace,
        box=hardware_request.assigned_box,
        evidence=evidence,
        remark="Immutable.",
        actor=admin,
    )
    accountability = RequesterAccountability.objects.create(
        requester=hardware_request.requester,
        request=hardware_request,
        request_item=item,
        makerspace=makerspace,
        issue_type=RequesterAccountability.IssueType.DAMAGED,
        evidence_photo=evidence,
        quantity=1,
        created_by=admin,
    )

    with pytest.raises(RuntimeError):
        event.save()
    with pytest.raises(RuntimeError):
        event.delete()
    with pytest.raises(RuntimeError):
        accountability.save()
    with pytest.raises(RuntimeError):
        accountability.delete()


def test_reusing_return_evidence_on_second_return_returns_400(monkeypatch):
    makerspace = make_space("return-reuse-evidence")
    admin = make_member("return-reuse-evidence-admin", makerspace)
    first_product = make_product(makerspace, name="Scope")
    second_product = make_product(makerspace, name="Meter")
    first_request = make_issued_request(makerspace, admin, [(first_product, 1)])
    second_request = make_issued_request(makerspace, admin, [(second_product, 1)])
    evidence = make_return_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))
    client = authenticated_client(admin)

    first = client.post(
        return_url(first_request),
        return_payload(first_request, evidence),
        format="json",
    )
    second = client.post(
        return_url(second_request),
        return_payload(second_request, evidence),
        format="json",
    )

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.data["code"] == "return_validation_error"
    assert second.data["detail"] == "Evidence already used."
    # The reviewed-return transaction durably marked the photo consumed.
    evidence.refresh_from_db()
    assert evidence.consumption_state == "consumed"


def test_return_items_raises_insufficient_stock_when_issued_too_low():
    makerspace = make_space("return-insufficient-issued")
    admin = make_member("return-insufficient-issued-admin", makerspace)
    product = make_product(
        makerspace,
        total_quantity=10,
        available_quantity=10,
        issued_quantity=0,
    )
    hardware_request = make_issued_request(makerspace, admin, [(product, 1)])
    product.issued_quantity = 0
    product.available_quantity = 9
    product.save(update_fields=["issued_quantity", "available_quantity", "updated_at"])
    item = hardware_request.items.get()

    with pytest.raises(InsufficientStock):
        with transaction.atomic():
            availability.return_items(
                hardware_request,
                [{"item": item, "returned": 1, "damaged": 0, "missing": 0}],
            )
