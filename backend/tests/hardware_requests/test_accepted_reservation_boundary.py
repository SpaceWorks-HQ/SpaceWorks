"""D7 guard: releasing an accepted request needs an approved transition."""

import pytest

from apps.audit.models import AuditLog
from apps.hardware_requests import workflow
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from tests.return_helpers import make_member, make_product, make_space, make_user

pytestmark = pytest.mark.django_db


def test_accepted_request_cannot_be_rejected_to_release_stock():
    makerspace = make_space("accepted-reservation-boundary")
    staff = make_member("reservation-staff", makerspace)
    borrower = make_user("reservation-borrower")
    product = make_product(makerspace)
    request = HardwareRequest.objects.create(
        makerspace=makerspace, requester=borrower, requester_username=borrower.username,
    )
    HardwareRequestItem.objects.create(request=request, product=product, requested_quantity=2)
    accepted = workflow.accept_request(staff, request)

    with pytest.raises(workflow.InvalidTransition):
        workflow.reject_request(staff, accepted, "Uncollected; cancel this loan.")

    request.refresh_from_db()
    product.refresh_from_db()
    assert request.status == HardwareRequest.Status.ACCEPTED
    assert (product.available_quantity, product.reserved_quantity, product.issued_quantity) == (8, 2, 0)
    assert AuditLog.objects.filter(action="request.accepted", target_id=str(request.pk)).count() == 1
    assert not AuditLog.objects.filter(action="request.rejected", target_id=str(request.pk)).exists()
