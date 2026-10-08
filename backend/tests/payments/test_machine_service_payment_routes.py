"""The machine-service mark-offline/waive routes agree with the generic reconciliation ones."""

import pytest

from apps.payments.models import Payment
from tests.payments.test_machine_payments import payment_for, service_request
from tests.return_helpers import authenticated_client, make_member, make_space, settlement_payload

pytestmark = pytest.mark.django_db


def _url(payment, action):
    return f"/api/v1/admin/machine-service/payments/{payment.pk}/{action}"


def test_waiving_an_already_settled_machine_charge_is_a_conflict_not_a_silent_200():
    space = make_space("ms-route-waive-conflict")
    manager = make_member("ms-route-waive-conflict-manager", space)
    payment = payment_for(service_request(space, manager), manager)
    client = authenticated_client(manager)

    settled = client.post(_url(payment, "mark-offline"), settlement_payload(), format="json")
    waived = client.post(_url(payment, "waive"), format="json")
    again = client.post(_url(payment, "mark-offline"), settlement_payload(), format="json")

    assert settled.status_code == 200, settled.data
    assert waived.status_code == 409 and waived.data["code"] == "payment_terminal"
    assert again.status_code == 409
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID_OFFLINE


def test_the_machine_route_refuses_a_settlement_without_a_receipt():
    space = make_space("ms-route-no-receipt")
    manager = make_member("ms-route-no-receipt-manager", space)
    payment = payment_for(service_request(space, manager), manager)

    response = authenticated_client(manager).post(_url(payment, "mark-offline"), {}, format="json")

    assert response.status_code == 400
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING


def test_waiving_a_pending_machine_charge_through_the_machine_route_still_works():
    space = make_space("ms-route-waive")
    manager = make_member("ms-route-waive-manager", space)
    payment = payment_for(service_request(space, manager), manager)

    response = authenticated_client(manager).post(_url(payment, "waive"), format="json")

    assert response.status_code == 200
    assert response.data["status"] == Payment.Status.WAIVED
