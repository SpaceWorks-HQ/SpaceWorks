"""R12: optional container selection and core box scans are separate contracts."""

import pytest
from django.test import override_settings

from apps.audit.models import AuditLog
from apps.boxes.models import Box
from apps.hardware_requests.models import PublicToolLoan
from apps.makerspaces.module_install import uninstall_module
from tests.test_box_checkout_integrity import (
    direct_payload,
    direct_url,
    eligible_member,
    make_admin,
    make_box_qr,
    make_product,
    make_space,
    member_client,
)

pytestmark = pytest.mark.django_db


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
@pytest.mark.parametrize("containers_on", [True, False])
def test_direct_handout_only_keeps_explicit_container_selection_when_module_on(containers_on):
    """Pin the current silent drop; changing it to a 400 remains an owner decision."""
    space = make_space(f"combo-container-field-{containers_on}")
    manager = make_admin(space)
    borrower = eligible_member(space)
    container = Box.objects.create(makerspace=space, label="Empty handout vessel")
    product = make_product(space)
    if not containers_on:
        uninstall_module(space, "containers")
    payload = direct_payload(
        space, borrower, container_id=container.pk,
        items=[{"product_id": product.pk, "quantity": 1}],
    )

    response = member_client(manager).post(direct_url(space), payload, format="json")

    assert response.status_code == 201, response.data
    loan = PublicToolLoan.objects.get(makerspace=space)
    expected_container = container.pk if containers_on else None
    assert loan.container_id == expected_container
    assert response.data["container_id"] == expected_container
    assert loan.request.issue_evidence_id == payload["evidence_id"]
    product.refresh_from_db()
    assert product.issued_quantity == 1
    assert AuditLog.objects.filter(
        makerspace=space, actor=manager, action="evidence.attached",
        meta__evidence_id=payload["evidence_id"],
    ).exists()


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_handout_box_scan_still_sets_container_with_containers_off():
    """A core scanner target wins after the optional selection field is dropped."""
    space = make_space("combo-container-off-box-scan")
    manager = make_admin(space)
    borrower = eligible_member(space)
    selected = Box.objects.create(makerspace=space, label="Ignored selection")
    scanned = Box.objects.create(makerspace=space, label="Scanned kit")
    product = make_product(space, box=scanned)
    qr = make_box_qr(space, scanned)
    uninstall_module(space, "containers")
    payload = direct_payload(
        space, borrower, container_id=selected.pk, qr_payloads=[qr.payload],
    )

    response = member_client(manager).post(direct_url(space), payload, format="json")

    assert response.status_code == 201, response.data
    loan = PublicToolLoan.objects.get(makerspace=space)
    assert loan.container_id == scanned.pk
    assert response.data["container_id"] == scanned.pk
    assert loan.qr_ids == [qr.pk]
    assert loan.request.issue_evidence_id == payload["evidence_id"]
    product.refresh_from_db()
    assert product.issued_quantity == 1
