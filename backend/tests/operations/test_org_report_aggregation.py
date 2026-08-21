from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.operations.org_report_aggregate import aggregate_rows
from apps.operations.org_report_scope import EXCLUDED_ORGANIZATION_REPORT_KEYS
from apps.operations.org_report_strategies import STRATEGIES
from apps.operations.org_reports import (
    InvalidOrganizationAggregationScope,
    organization_report_data,
)
from apps.operations.report_registry import REPORT_REGISTRY, ReportResult, report_definition
from apps.operations.report_scope import combined_report_scope, single_report_scope


pytestmark = pytest.mark.django_db


def _space(slug):
    return Makerspace.objects.create(name=slug.title(), slug=slug)


def _user(slug):
    return User.objects.create_user(username=slug)


def _scope(*spaces):
    return combined_report_scope(Makerspace.objects.filter(pk__in=[space.pk for space in spaces]))


def test_strategy_registry_covers_every_supported_key_and_declares_every_field():
    assert set(STRATEGIES) == set(REPORT_REGISTRY) - EXCLUDED_ORGANIZATION_REPORT_KEYS
    for key, strategy in STRATEGIES.items():
        definition = REPORT_REGISTRY[key]
        if definition.summary:
            continue
        assert set(strategy.total_fields) | set(strategy.breakdown_only_fields) == set(
            definition.fields
        )


def test_sum_strategy_adds_two_makerspace_summaries():
    rows = [(1, [{"products": 2, "assets": 3, "active_loans": 1, "available_quantity": 7,
                  "issued_quantity": 2, "damaged_quantity": 1, "missing_quantity": 0}]),
            (2, [{"products": 5, "assets": 4, "active_loans": 2, "available_quantity": 11,
                  "issued_quantity": 3, "damaged_quantity": 0, "missing_quantity": 1}])]

    total = aggregate_rows("summary", rows, limit=100)[0]

    assert total == {"products": 7, "assets": 7, "active_loans": 3,
                     "available_quantity": 18, "issued_quantity": 5,
                     "damaged_quantity": 1, "missing_quantity": 1}


def test_group_sum_strategy_regroups_current_dimensions():
    rows = [(1, [{"context": "issue", "count": 2}]),
            (2, [{"context": "issue", "count": 5}, {"context": "return", "count": 3}])]

    assert aggregate_rows("qr-scans", rows, limit=100) == [
        {"context": "issue", "count": 7},
        {"context": "return", "count": 3},
    ]


def test_row_union_reranks_distinct_products_after_per_space_limit():
    rows = [
        (1, [{"product_name": "First", "times_lent": 4, "total_quantity_lent": 4},
             {"product_name": "Cut", "times_lent": 1, "total_quantity_lent": 50}]),
        (2, [{"product_name": "Winner", "times_lent": 8, "total_quantity_lent": 8}]),
    ]

    assert aggregate_rows("most-lent", rows, limit=1) == [
        {"product_name": "Winner", "times_lent": 8, "total_quantity_lent": 8}
    ]


def test_weighted_rate_recomputes_and_is_not_mean_of_space_rates():
    rows = [
        (1, [{"status": "completed", "capacity": 10, "registrations": 1,
             "confirmed": 1, "registered": 0, "waitlisted": 0,
             "cancelled": 0, "attended": 1, "attendance_rate_percent": 100.0}]),
        (2, [{"status": "completed", "capacity": 20, "registrations": 9,
             "confirmed": 9, "registered": 9, "waitlisted": 0,
             "cancelled": 0, "attended": 0, "attendance_rate_percent": 0.0}]),
    ]

    total = aggregate_rows("event-attendance", rows, limit=100)[0]

    assert total["attendance_rate_percent"] == 10.0
    assert total["attendance_rate_percent"] != 50.0


def test_global_rank_regroups_same_requester_across_two_spaces():
    first, second = _space("rank-first"), _space("rank-second")
    shared, other = _user("rank-shared"), _user("rank-other")
    for space, requester, quantity in ((first, shared, 2), (second, shared, 3), (first, other, 4)):
        product = InventoryProduct.objects.create(
            makerspace=space, name=f"Product {space.pk} {requester.pk}", total_quantity=10,
            available_quantity=10,
        )
        request = HardwareRequest.objects.create(
            makerspace=space, requester=requester, requester_username=requester.username,
            status=HardwareRequest.Status.ISSUED, issued_at=timezone.now(),
        )
        HardwareRequestItem.objects.create(
            request=request, product=product, requested_quantity=quantity,
            accepted_quantity=quantity, issued_quantity=quantity,
        )

    data = organization_report_data(
        report_definition("top-borrowers"), _scope(first, second), limit=10
    )

    assert data["total"]["rows"][0] == {
        "holder": shared.username, "requests": 2, "items_borrowed": 5,
    }


def test_distinct_person_counts_one_member_in_two_spaces_once():
    first, second = _space("people-first"), _space("people-second")
    shared = _user("people-shared")
    now = timezone.now()
    for space in (first, second):
        MakerspaceMembership.objects.create(
            makerspace=space, user=shared, status="active",
            activated_at=now, verified_at=now,
        )

    data = organization_report_data(
        report_definition("member-activity"), _scope(first, second),
        limit=10, date_range=(now - timedelta(days=1), now + timedelta(days=1)),
    )
    total = data["total"]["rows"][0]

    assert total["new_members"] == 1
    assert total["active_members"] == 1
    assert total["verified_members"] == 1


@pytest.mark.parametrize("report_key", sorted(STRATEGIES))
def test_every_supported_key_always_carries_breakdown_and_total(monkeypatch, report_key):
    space = _space(f"shape-{report_key}")
    definition = report_definition(report_key)

    def fake_builder(_definition):
        if definition.summary:
            return lambda *_args, **_kwargs: []
        return lambda *_args, **_kwargs: ReportResult(definition.fields, [])

    monkeypatch.setattr(type(definition), "builder", fake_builder)
    data = organization_report_data(definition, _scope(space), limit=10)

    assert set(data) == {"report_key", "strategy", "breakdown", "total"}
    assert data["breakdown"] == [{"makerspace_id": space.id, "rows": []}]
    assert set(data["total"]) == {"rows"}


def test_empty_combined_scope_never_calls_builder_or_widens(monkeypatch):
    definition = report_definition("summary")
    monkeypatch.setattr(
        type(definition), "builder",
        lambda _self: pytest.fail("empty organization scope called a report builder"),
    )

    data = organization_report_data(
        definition, combined_report_scope(Makerspace.objects.none()), limit=10
    )

    assert data["breakdown"] == []
    assert data["total"] == {"rows": []}


def test_only_combined_scope_can_flatten_an_organization_total():
    space = _space("single-cannot-flatten")

    with pytest.raises(InvalidOrganizationAggregationScope):
        organization_report_data(
            report_definition("summary"), single_report_scope(space), limit=10
        )


def test_distinct_person_reconciles_a_pre_signup_invite_with_the_later_account():
    """Stage 4 [P2]: the same human invited before and after signup must count ONCE.

    The pre-signup invitation is email-keyed and the later account-backed row is
    user-keyed, so without reconciliation one person counts twice -- the exact error a
    distinct-person metric exists to prevent.
    """
    from apps.makerspaces.models import MembershipRequest
    from apps.operations.org_report_identity import _distinct_people

    early = _space("identity-recon-early")
    later = _space("identity-recon-later")
    shared_email = "Same.Person@example.com"
    person = User.objects.create_user(
        username="identity-recon-person", email=shared_email.lower()
    )

    MembershipRequest.objects.create(makerspace=early, invite_email=shared_email)
    MembershipRequest.objects.create(makerspace=later, user=person)

    scope = _scope(early, later)
    counted = _distinct_people(
        MembershipRequest.objects.filter(makerspace_id__in=scope.makerspace_ids)
    )

    assert counted == 1
