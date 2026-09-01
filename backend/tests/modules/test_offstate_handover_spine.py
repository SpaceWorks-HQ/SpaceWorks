"""Focused route-gate checks for the reviewed-request spine past `accepted`.

The full core-independence spine now performs a legitimate assign, issue, and return.
These smaller checks keep the original defect's boundary explicit: admin handover URLs
must reach workflow validation even when the optional guest console is absent.
"""

import pytest
from django.urls import reverse

from apps.hardware_requests.models import HardwareRequest
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import core_module_keys
from tests.makerspaces.test_core_module_independence import _client, _requester, _staff

pytestmark = pytest.mark.django_db
CORE = sorted(core_module_keys())

# The three transitions that move a reviewed request past `accepted`.
POST_ACCEPT_ROUTES = ("request-assign-box", "request-issue", "request-return")


def _accepted_request(slug, modules):
    space = Makerspace.objects.create(
        name=slug, slug=slug, enabled_modules=sorted(modules),
        public_inventory_enabled=True,
    )
    product = InventoryProduct.objects.create(
        makerspace=space, name="Torque wrench", total_quantity=3,
        available_quantity=3, is_public=True,
    )
    submit = _client(_requester(slug, space)).post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        {"requested_for": "Spine", "items": [{"product_id": product.pk, "quantity": 1}]},
        format="json",
    )
    assert submit.status_code == 201, submit.data
    staff = _client(_staff(slug))
    pending = staff.get(reverse("hardware_requests:pending-requests", args=[space.id]))
    request_id = pending.data["results"][0]["id"]
    accept = staff.post(
        reverse("hardware_requests:request-accept", args=[request_id]), {}, format="json"
    )
    assert accept.status_code == 200, accept.data
    return space, staff, request_id


def test_core_only_install_can_move_a_reviewed_request_past_accepted():
    """`request_workflow` is CORE; no optional module may gate its transitions."""
    space, staff, request_id = _accepted_request("handover-spine-core-only", CORE)
    assert "guest_handover" not in space.enabled_modules

    for name in POST_ACCEPT_ROUTES:
        response = staff.post(
            reverse(f"hardware_requests:{name}", args=[request_id]), {}, format="json"
        )
        # The Hard Rules may still refuse (a box QR scan and an issue photo are
        # required) -- but the refusal must never be an optional module's gate.
        assert "guest_handover" not in str(response.data), (name, response.data)


def test_guest_handover_on_lets_the_same_request_reach_the_evidence_rules():
    """Control: with the module on, the next refusal is the Hard Rule, not the gate."""
    _space, staff, request_id = _accepted_request(
        "handover-spine-module-on", CORE + ["guest_handover"]
    )

    response = staff.post(
        reverse("hardware_requests:request-issue", args=[request_id]), {}, format="json"
    )

    assert "guest_handover" not in str(response.data)
    assert "evidence_id" in str(response.data), response.data
    assert HardwareRequest.objects.get(pk=request_id).status == (
        HardwareRequest.Status.ACCEPTED
    )
