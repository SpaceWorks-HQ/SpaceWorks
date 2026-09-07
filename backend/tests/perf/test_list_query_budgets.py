"""Query budgets for the hot list endpoints.

Each test seeds more rows than one page holds and asserts the request stays under a fixed
number of queries. A budget is a ceiling, not a target: the point is that adding a
``SerializerMethodField`` that hits the database per row turns a 6-query page into a
30-query page, and this file is what turns that into a red build instead of a slow queue.
Budgets are generous on purpose so a legitimate extra lookup does not need a ritual edit.
"""
import pytest
from django.urls import reverse

from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import MakerspaceMembership
from apps.operations.models import StockTransfer
from tests.return_helpers import (
    authenticated_client,
    make_accepted_request,
    make_issued_request,
    make_member,
    make_product,
    make_space,
    make_user,
)

pytestmark = pytest.mark.django_db

ROWS = 30  # more than one PageNumberPagination page (24)
# Measured 2026-09-03: the staff endpoints cost a constant ~20 queries (session/JWT auth,
# membership + role resolution, module and servability checks, count + page) regardless of
# row count. An N+1 on a 30-row seed would put them at 50+, so 24 catches it with headroom.
BUDGET = 24


@pytest.fixture
def space():
    return make_space("budget-space")


@pytest.fixture
def manager(space):
    return make_member("budget-manager", space)


@pytest.fixture
def client(manager):
    return authenticated_client(manager)


def _products(space, n=ROWS):
    return [
        make_product(space, name=f"Tool {i:02d}", total_quantity=5, available_quantity=5)
        for i in range(n)
    ]


def _assert_page(response):
    assert response.status_code == 200, response.content[:300]
    payload = response.json()
    if isinstance(payload, dict) and "results" in payload:
        assert payload["count"] >= 1
    return payload


def test_public_inventory_list(space, django_assert_max_num_queries):
    _products(space)
    url = reverse("public-inventory", kwargs={"makerspace_slug": space.slug})
    from rest_framework.test import APIClient

    with django_assert_max_num_queries(BUDGET):
        _assert_page(APIClient().get(url))


def test_admin_inventory_list(space, client, django_assert_max_num_queries):
    _products(space)
    url = reverse("admin-inventory", kwargs={"makerspace_id": space.pk})
    with django_assert_max_num_queries(BUDGET):
        _assert_page(client.get(url))


def test_pending_requests_queue(space, client, django_assert_max_num_queries):
    for product in _products(space):
        request = make_accepted_request(space, product, 1)
        HardwareRequest.objects.filter(pk=request.pk).update(
            status=HardwareRequest.Status.PENDING_APPROVAL
        )
    url = reverse("hardware_requests:pending-requests", kwargs={"makerspace_id": space.pk})
    with django_assert_max_num_queries(BUDGET):
        _assert_page(client.get(url))


def test_accepted_requests_queue(space, client, django_assert_max_num_queries):
    for product in _products(space):
        make_accepted_request(space, product, 1)
    url = reverse("hardware_requests:accepted-requests", kwargs={"makerspace_id": space.pk})
    with django_assert_max_num_queries(BUDGET):
        _assert_page(client.get(url))


def test_active_loans_list(space, manager, client, django_assert_max_num_queries):
    for product in _products(space, n=12):
        make_issued_request(space, manager, [(product, 1)])
    url = reverse("hardware_requests:active-loans", kwargs={"makerspace_id": space.pk})
    with django_assert_max_num_queries(BUDGET):
        _assert_page(client.get(url))


def test_containers_list(space, client, django_assert_max_num_queries):
    from tests.return_helpers import make_box

    for i in range(ROWS):
        make_box(space, label=f"Box {i:02d}")
    url = reverse("containers", kwargs={"makerspace_id": space.pk})
    with django_assert_max_num_queries(BUDGET):
        _assert_page(client.get(url))


def test_stock_transfers_list(space, manager, client, django_assert_max_num_queries):
    for i in range(ROWS):
        StockTransfer.objects.create(
            makerspace=space, source_makerspace=space, created_by=manager,
            reason=f"transfer {i}"
        )
    url = reverse("stock-transfers", kwargs={"makerspace_id": space.pk})
    with django_assert_max_num_queries(BUDGET):
        _assert_page(client.get(url))


def test_membership_list(space, client, django_assert_max_num_queries):
    for i in range(ROWS):
        MakerspaceMembership.objects.create(
            user=make_user(f"member-{i:02d}"), makerspace=space,
            role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        )
    url = reverse("admin-membership-list-create", kwargs={"makerspace_id": space.pk})
    with django_assert_max_num_queries(BUDGET):
        _assert_page(client.get(url))
