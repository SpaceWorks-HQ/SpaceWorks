"""Matrix cells M14–M16: waiver state and verification at a real borrowing surface.

The predicates are tested elsewhere; these pin the COMPOSED behaviour at request submission:
a superseded waiver refuses until re-accepted, a witnessed acceptance of the current version
admits, and verification changes nothing in either direction.
"""
import pytest
from django.test import override_settings
from django.urls import reverse

from apps.inventory.models import InventoryProduct
from apps.makerspaces import membership_services, waiver_services
from apps.makerspaces.models import MakerspaceMembership
from apps.presence import services as presence
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db(transaction=True)


def _submit(makerspace, person):
    """Submit a borrow request; one product and one presence session per member."""
    try:
        presence.start_session(person, makerspace, 60)
    except Exception:  # noqa: BLE001 - a session may already be open from an earlier call
        pass
    product, _ = InventoryProduct.objects.get_or_create(
        makerspace=makerspace, name=f"Scope {person.pk}",
        defaults={"total_quantity": 5, "available_quantity": 5, "is_public": True},
    )
    return authenticated_client(person).post(
        reverse("hardware_requests:request-submit", args=[makerspace.slug]),
        {"requested_for": "Bench", "items": [{"product_id": product.pk, "quantity": 1}]},
        format="json",
    )


def _member(makerspace, name):
    person = user(name)
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=person, assigned_role=member_role(makerspace), role="custom",
    )
    return person, membership


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_a_superseded_waiver_refuses_until_the_new_version_is_accepted():
    makerspace = space("matrix-waiver-stale")
    boss = manager(makerspace, "matrix-waiver-stale-manager")
    person, membership = _member(makerspace, "matrix-waiver-stale-member")
    waiver_services.publish_waiver(boss, makerspace, "Be careful.", "v1")
    waiver_services.accept_waiver(membership)
    assert _submit(makerspace, person).status_code == 201

    waiver_services.publish_waiver(boss, makerspace, "Be more careful.", "v2")
    refused = _submit(makerspace, person)
    assert refused.status_code == 403, refused.data
    assert refused.data["code"] == "waiver_acceptance_required"

    waiver_services.accept_waiver(membership)
    assert _submit(makerspace, person).status_code == 201


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_a_witnessed_acceptance_of_the_current_version_admits():
    makerspace = space("matrix-waiver-witness")
    boss = manager(makerspace, "matrix-waiver-witness-manager")
    person, membership = _member(makerspace, "matrix-waiver-witness-member")
    waiver_services.publish_waiver(boss, makerspace, "Be careful.", "v1")
    assert _submit(makerspace, person).status_code == 403

    waiver_services.witness_waiver_acceptance(boss, membership.pk)

    assert _submit(makerspace, person).status_code == 201


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_verification_gates_nothing_in_either_direction():
    makerspace = space("matrix-verification")
    boss = manager(makerspace, "matrix-verification-manager")
    unverified, _ = _member(makerspace, "matrix-verification-plain")
    verified, verified_membership = _member(makerspace, "matrix-verification-badge")
    membership_services.verify_member(boss, verified_membership)
    waiver_services.publish_waiver(boss, makerspace, "Be careful.", "v1")

    # Verified is a badge: it does not excuse a missing waiver...
    assert _submit(makerspace, verified).status_code == 403
    # ...and not being verified does not stop a member who has accepted it.
    waiver_services.accept_waiver(MakerspaceMembership.objects.get(makerspace=makerspace, user=unverified))
    assert _submit(makerspace, unverified).status_code == 201
