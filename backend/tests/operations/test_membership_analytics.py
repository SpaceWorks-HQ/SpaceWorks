"""Counts-only cohorts and local-month recurring-plan projections."""

from datetime import datetime, UTC
from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership, MembershipPlan, MembershipTerm
from apps.operations import reports
from apps.operations.reports_retention import build_member_retention
from apps.operations.reports_membership_revenue import build_membership_revenue
from apps.payments.models import Payment
from tests.module_helpers import disable_module
from apps.makerspaces.module_install import install_module as enable_module
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db


def at(value):
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def member(space, name, joined, **extra):
    user = make_member(name, space)
    MakerspaceMembership.objects.filter(user=user, makerspace=space).update(
        activated_at=joined, created_at=joined, **extra,
    )
    return user.makerspace_memberships.get(makerspace=space)


def term(space, membership, name, start, end, *, amount="30", interval="monthly", currency="usd", status="active"):
    plan = MembershipPlan.objects.create(
        makerspace=space, name=name, amount=amount, interval=interval, currency=currency,
        custom_days=10 if interval == "custom_days" else None,
    )
    return MembershipTerm.objects.create(membership=membership, plan=plan, starts_at=start, ends_at=end, status=status)


def event(space, membership, action, instant):
    AuditLog.objects.create(makerspace=space, action=action, target_type=membership._meta.label_lower,
                            target_id=str(membership.pk), created_at=instant, meta={"reason": "PRIVATE REASON"})


def test_cohort_uses_local_join_month_and_only_mature_anniversaries():
    space = make_space("cohort-local")
    space.timezone = "Asia/Kolkata"
    space.save(update_fields=["timezone"])
    joined = at("2025-01-31T20:00:00")  # February locally.
    member(space, "cohort-retained", joined)
    member(space, "cohort-churned", joined, status="revoked", revoked_at=at("2025-04-01"), revocation_reason="PRIVATE REASON")
    member(space, "cohort-young", at("2025-02-28"))
    member(space, "cohort-future", at("2027-01-01"))

    result = build_member_retention(space.pk, months=3, now=at("2025-05-05"))

    assert result.records == [{"cohort_month": "2025-02", "months_after_join": 3,
        "cohort_members": 3, "eligible_members": 2, "retained_members": 1,
        "retention_percent": Decimal(50), "churned_members": 1, "reactivated_members": 0}]
    assert "cohort-retained" not in str(result) and "PRIVATE REASON" not in str(result)
    defaults = build_member_retention(space.pk, now=at("2025-05-05"))
    assert [row["months_after_join"] for row in defaults.records] == [3, 6, 12]
    assert defaults.records[-1]["retention_percent"] is None


def test_cohort_recovers_original_join_and_reactivation_from_append_only_audits():
    space = make_space("cohort-history")
    membership = member(space, "cohort-history-member", at("2025-03-01"))
    event(space, membership, "membership.joined", at("2025-01-01"))
    event(space, membership, "membership.revoked", at("2025-02-01"))
    event(space, membership, "membership.approved", at("2025-03-01"))
    event(space, membership, "membership.approved", at("2025-03-05"))  # Role change, not a second join.

    row = build_member_retention(space.pk, months=3, now=at("2025-07-01")).records[0]

    assert row["cohort_month"] == "2025-01"
    assert (row["retained_members"], row["churned_members"], row["reactivated_members"]) == (1, 1, 1)


def test_mrr_normalizes_yearly_plans_keeps_currencies_separate_and_counts_members_once():
    space = make_space("mrr-maths")
    space.timezone = "Asia/Kolkata"
    space.save(update_fields=["timezone"])
    start, end = at("2026-01-01"), at("2027-01-01")
    monthly = member(space, "mrr-monthly", start)
    annual = member(space, "mrr-annual", start)
    euro = member(space, "mrr-euro", start)
    waived = member(space, "mrr-waived", start)
    term(space, monthly, "Monthly", start, end)
    term(space, monthly, "Overlapping", start, end)
    term(space, annual, "Annual", start, end, amount="120", interval="yearly")
    term(space, euro, "Euro", start, end, amount="60", currency="eur")
    excluded = term(space, waived, "Waived", start, end, amount="100")
    Payment.objects.create(makerspace=space, subject_type="membership_term", subject_id=excluded.pk,
                           member=waived.user, created_by=waived.user,
                           amount=100, currency="usd", status="waived")
    term(space, monthly, "Custom", start, end, amount="999", interval="custom_days")
    result = build_membership_revenue(space.pk, date_range=(at("2026-02-01"), at("2026-03-01")), now=at("2026-04-01"))
    rows = {row["currency"]: row for row in result.records}

    assert rows["usd"]["recurring_members"] == 2
    assert (rows["usd"]["mrr"], rows["usd"]["arr"], rows["usd"]["arpu"]) == (Decimal(40), Decimal(480), Decimal(20))
    assert rows["eur"]["mrr"] == Decimal(60)
    assert all(row["period"] == "2026-02-01" for row in result.records)
    assert "mrr-monthly" not in str(result)


def test_mrr_churn_reactivation_and_contiguous_renewals():
    space = make_space("mrr-gaps")
    space.timezone = "UTC"
    space.save(update_fields=["timezone"])
    membership = member(space, "mrr-gaps-member", at("2026-01-01"))
    term(space, membership, "First", at("2026-01-01"), at("2026-02-01"), amount="10", status="expired")
    term(space, membership, "Returned", at("2026-03-01"), at("2026-04-01"), amount="10", status="expired")
    term(space, membership, "Renewed", at("2026-04-01"), at("2026-05-01"), amount="10")
    rows = {row["period"]: row for row in build_membership_revenue(space.pk, now=at("2026-04-15")).records}

    assert rows["2026-02-01"]["mrr"] == 0
    assert rows["2026-02-01"]["churned_members"] == 1
    assert rows["2026-03-01"]["reactivated_members"] == 1
    assert rows["2026-04-01"]["reactivated_members"] == 0
    assert rows["2026-04-01"]["churned_members"] == 0


def test_mrr_local_snapshot_includes_term_starting_before_local_month_end():
    space = make_space("mrr-boundary")
    space.timezone = "Asia/Kolkata"
    space.save(update_fields=["timezone"])
    membership = member(space, "mrr-boundary-member", at("2026-01-31T17:00:00"))
    term(space, membership, "Boundary", at("2026-01-31T17:00:00"), at("2026-02-01T17:00:00"))
    row = build_membership_revenue(space.pk, now=at("2026-02-01")).records[0]
    assert row["period"] == "2026-01-01" and row["mrr"] == 30


def test_analytics_scope_module_off_and_aggregate_pii_absence():
    space, other = make_space("analytics-own"), make_space("analytics-other")
    enable_module(space, "membership")
    enable_module(other, "membership")
    actor = make_member("analytics-manager", space)
    stranger = member(other, "SECRET-OTHER", at("2025-01-01"))
    term(other, stranger, "SecretPlan", at("2025-01-01"), at("2027-01-01"))
    client = authenticated_client(actor)
    for key in ["member-retention", "membership-revenue"]:
        assert client.get(f"/api/v1/admin/makerspace/{other.pk}/analytics/{key}").status_code == 404
        response = client.get(f"/api/v1/admin/makerspace/{space.pk}/analytics/{key}")
        assert response.status_code == 200, response.data
        assert "SECRET-OTHER" not in str(response.data)
        aggregate = reports.report_data(key)
        assert "makerspace_id" in aggregate["rows"][0]
        assert "SECRET-OTHER" not in str(aggregate)
        assert not ({"email", "phone", "username", "member_id", "revocation_reason"} & set(aggregate["rows"][0]))
    disable_module(space, "membership")
    assert client.get(f"/api/v1/admin/makerspace/{space.pk}/analytics/member-retention").status_code == 400
    assert client.get(f"/api/v1/admin/makerspace/{space.pk}/reports/membership-revenue/export").status_code == 400


def test_retention_filter_validation_and_mrr_default_month_grain():
    space = make_space("analytics-filters")
    enable_module(space, "membership")
    actor = make_member("analytics-filters-manager", space)
    client = authenticated_client(actor)
    path = f"/api/v1/admin/makerspace/{space.pk}/analytics"
    for invalid in ["0", "121", "three"]:
        assert client.get(f"{path}/member-retention?months={invalid}").status_code == 400
    assert client.get(f"{path}/membership-revenue").data["meta"]["grain"] == "month"


def test_hidden_makerspace_staff_can_read_their_report_without_deployment_disclosure():
    space = make_space("analytics-hidden")
    enable_module(space, "membership")
    actor = make_member("analytics-hidden-manager", space)
    membership = actor.makerspace_memberships.get(makerspace=space)
    membership.activated_at = at("2025-01-01")
    membership.save(update_fields=["activated_at"])
    term(space, membership, "HiddenPlan", at("2025-01-01"), at("2027-01-01"))
    space.superadmin_access_enabled = False
    space.save(update_fields=["superadmin_access_enabled"])
    client = authenticated_client(actor)
    for key in ["member-retention", "membership-revenue"]:
        response = client.get(f"/api/v1/admin/makerspace/{space.pk}/analytics/{key}")
        assert response.status_code == 200, response.data
        assert response.data["typed_rows"]
        assert all(row["makerspace_id"] != space.pk for row in reports.report_data(key)["typed_rows"])


def test_mrr_preserves_cancelled_term_history_only_until_audited_cancellation():
    space = make_space("mrr-cancel-history")
    space.timezone = "UTC"
    space.save(update_fields=["timezone"])
    membership = member(space, "mrr-cancel-member", at("2026-01-01"))
    cancelled = term(space, membership, "Cancelled", at("2026-01-01"), at("2027-01-01"), status="cancelled")
    AuditLog.objects.create(makerspace=space, action="membership.term_cancelled",
                            target_type=cancelled._meta.label_lower, target_id=str(cancelled.pk), created_at=at("2026-02-15"))
    rows = {row["period"]: row for row in build_membership_revenue(space.pk, now=at("2026-03-01")).records}
    assert rows["2026-01-01"]["mrr"] == 30
    assert rows["2026-02-01"]["mrr"] == 0
    assert rows["2026-02-01"]["churned_members"] == 1


def test_legacy_join_timestamp_survives_a_later_role_only_approval():
    space = make_space("cohort-legacy-approval")
    membership = member(space, "cohort-legacy-member", at("2025-01-01"))
    event(space, membership, "membership.approved", at("2025-06-01"))
    row = build_member_retention(space.pk, months=3, now=at("2025-07-01")).records[0]
    assert row["cohort_month"] == "2025-01" and row["retained_members"] == 1


def test_annual_projection_rounds_outputs_after_computing_arr():
    space = make_space("mrr-rounding")
    membership = member(space, "mrr-rounding-member", at("2026-01-01"))
    term(space, membership, "AnnualFraction", at("2026-01-01"), at("2027-01-01"), amount="100", interval="yearly")
    row = build_membership_revenue(space.pk, now=at("2026-02-01")).records[0]
    assert row["mrr"] == Decimal("8.33")
    assert row["arr"] == Decimal("100.00")


def test_mrr_mid_month_range_excludes_earlier_churn_and_reactivation():
    space = make_space("mrr-mid-month")
    space.timezone = "UTC"
    space.save(update_fields=["timezone"])
    membership = member(space, "mrr-mid-month-member", at("2026-01-01"))
    term(space, membership, "Before", at("2026-01-01"), at("2026-02-02"), status="expired")
    term(space, membership, "After", at("2026-02-05"), at("2026-04-01"))
    row = build_membership_revenue(space.pk,
        date_range=(at("2026-02-15"), at("2026-03-01")), now=at("2026-04-01")).records[0]
    assert row["mrr"] == 30
    assert row["churned_members"] == row["reactivated_members"] == 0


@pytest.mark.parametrize("parameter,value", [("start", "2026-02-30"), ("start", "2026-13-01"), ("end", "9999-12-31")])
def test_invalid_calendar_dates_return_400(parameter, value):
    space = make_space("analytics-invalid-date")
    enable_module(space, "membership")
    client = authenticated_client(make_member("analytics-invalid-date-manager", space))
    for surface in ["analytics/member-retention", "reports/membership-revenue/export"]:
        assert client.get(f"/api/v1/admin/makerspace/{space.pk}/{surface}?{parameter}={value}").status_code == 400
