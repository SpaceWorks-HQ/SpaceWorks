import pytest

from apps.accounts.claim_route_types import BODY_OBJECT, ID, PUBLIC_TOKEN, SLUG
from apps.accounts.claim_tenants import claim_tenant_matches, resolve_claim_tenant
from apps.bookings.models import BookableSpace
from apps.machines.models import Machine, MachineType
from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db


def test_slug_and_id_resolvers_return_the_exact_makerspace():
    space = Makerspace.objects.create(name="Claim tenant", slug="claim-tenant")

    assert resolve_claim_tenant(
        SLUG,
        view_name="presence-start",
        url_kwargs={"makerspace_slug": space.slug},
    ) == space
    assert resolve_claim_tenant(
        ID,
        view_name="member-profile",
        url_kwargs={"makerspace_id": space.pk},
    ) == space


def test_public_token_and_body_object_resolve_row_ownership():
    space = Makerspace.objects.create(name="Owner", slug="owner")
    bookable = BookableSpace.objects.create(makerspace=space, name="Bench")
    machine_type = MachineType.objects.create(
        makerspace=space, slug="mill", name="Mill"
    )
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Mill one"
    )

    assert resolve_claim_tenant(
        PUBLIC_TOKEN,
        view_name="public-booking-submit",
        url_kwargs={"public_token": bookable.public_token},
    ) == space
    assert resolve_claim_tenant(
        BODY_OBJECT,
        view_name="public-machine-service-request-submit",
        url_kwargs={},
        body={"machine_id": machine.pk},
    ) == space


def test_match_is_strictly_owner_equality_without_cross_tenant_routing():
    owner = Makerspace.objects.create(name="Owner", slug="strict-owner")
    claim_space = Makerspace.objects.create(name="Claim", slug="strict-claim")
    bookable = BookableSpace.objects.create(makerspace=owner, name="Foreign bench")

    assert not claim_tenant_matches(
        PUBLIC_TOKEN,
        claim_makerspace_id=claim_space.pk,
        view_name="public-booking-submit",
        url_kwargs={"public_token": bookable.public_token},
    )

