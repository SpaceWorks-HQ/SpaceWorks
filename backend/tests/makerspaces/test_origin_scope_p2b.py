from types import SimpleNamespace

import pytest
from django.test import RequestFactory
from django.urls import resolve, reverse

from apps.accounts.models import User
from apps.machines.models import MachineServiceRequest, MachineType, ServiceQueue
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.origin_scope import staff_origin_scope_allows
from apps.makerspaces.origin_scope_routes import request_route_targets
from apps.payments.models import Payment


pytestmark = pytest.mark.django_db


def _space(slug):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        frontend_domain=f"{slug}.example.test",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )


def _user(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )


def _origin_request(url, space, *, query=None):
    request = RequestFactory().get(
        url,
        query or {},
        HTTP_ORIGIN=f"https://{space.frontend_domain}",
    )
    request.resolver_match = resolve(request.path_info)
    return request


def _service_request(space, requester):
    machine_type = MachineType.objects.create(
        makerspace=space, slug="p2b-printer", name="P2b printer"
    )
    queue = ServiceQueue.objects.create(
        makerspace=space,
        machine_type=machine_type,
        name="P2b queue",
    )
    return MachineServiceRequest.objects.create(
        makerspace=space,
        requester=requester,
        queue=queue,
        title="P2b job",
    )


def test_registered_object_route_rejects_cross_tenant_path_even_with_own_hint():
    space_a = _space("p2b-origin-a")
    space_b = _space("p2b-origin-b")
    target = MakerspaceMembership.objects.create(
        makerspace=space_b,
        user=_user("p2b-cross-target"),
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    request = _origin_request(
        reverse("admin-membership-capabilities", args=[target.pk]),
        space_a,
        query={"makerspace_id": space_a.pk},
    )

    assert staff_origin_scope_allows(request) is False


def test_new_scalar_object_routes_resolve_from_their_own_origin():
    space = _space("p2b-own-origin")
    requester = _user("p2b-route-requester")
    service_request = _service_request(space, requester)
    payment = Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=service_request.pk,
        member=requester,
        amount="10.00",
        currency="usd",
        created_by=requester,
    )
    membership = MakerspaceMembership.objects.create(
        makerspace=space,
        user=_user("p2b-route-member"),
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    routes = (
        ("admin-machine-service-request-reprint", service_request.pk),
        ("admin-machine-service-payment-mark-offline", payment.pk),
        ("admin-machine-service-payment-waive", payment.pk),
        ("admin-membership-capabilities", membership.pk),
    )

    for url_name, pk in routes:
        request = _origin_request(reverse(url_name, args=[pk]), space)
        assert staff_origin_scope_allows(request) is True, url_name


def test_password_reset_target_set_must_fit_entirely_inside_origin_scope():
    space_a = _space("p2b-password-a")
    space_b = _space("p2b-password-b")
    target = _user("p2b-password-target")
    for space in (space_a, space_b):
        MakerspaceMembership.objects.create(
            makerspace=space,
            user=target,
            role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        )
    request = _origin_request(
        reverse("admin-user-reset-password", args=[target.pk]), space_a
    )

    url_name, targets, invalid, recognized = request_route_targets(request)

    assert url_name == "admin-user-reset-password"
    assert targets == {space_a.pk, space_b.pk}
    assert invalid is False
    assert recognized is True
    assert staff_origin_scope_allows(request) is False


def test_password_reset_single_tenant_target_resolves_from_its_own_origin():
    space = _space("p2b-password-own")
    target = _user("p2b-password-own-target")
    MakerspaceMembership.objects.create(
        makerspace=space,
        user=target,
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    request = _origin_request(
        reverse("admin-user-reset-password", args=[target.pk]), space
    )

    assert staff_origin_scope_allows(request) is True


def test_unregistered_route_cannot_turn_a_query_hint_into_an_origin_grant():
    space = _space("p2b-unregistered")
    request = RequestFactory().get(
        "/api/v1/admin/unregistered/42",
        {"makerspace_id": space.pk},
        HTTP_ORIGIN=f"https://{space.frontend_domain}",
    )
    request.resolver_match = SimpleNamespace(
        url_name="p2b-unregistered-object", kwargs={"pk": 42}
    )

    assert staff_origin_scope_allows(request) is False


def test_explicit_query_scoped_listing_still_uses_its_makerspace_filter():
    space = _space("p2b-query-list")
    request = _origin_request(
        reverse("admin-audit-logs"),
        space,
        query={"makerspace": space.pk},
    )

    assert staff_origin_scope_allows(request) is True
