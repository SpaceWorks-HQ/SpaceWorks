from datetime import timedelta
from io import BytesIO

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.models import User
from apps.makerspaces.models import MakerspaceMembership, MembershipRequest
from apps.operations import reports
from tests.return_helpers import authenticated_client, make_member, make_space, make_user


pytestmark = pytest.mark.django_db
MEMBER_ACTIVITY_FIELDS = (
    "makerspace_name", "membership_policy", "referrals_enabled", "new_members",
    "active_members", "revoked_members", "pending_requests", "open_invites",
    "referred_joins", "verified_members",
)


def test_member_activity_has_one_scoped_row_with_current_snapshot_metrics():
    space = make_space("member-activity")

    data = reports.report_data("member-activity", space.id)

    assert data["rows"] == [[
        "makerspace_name", "membership_policy", "referrals_enabled", "new_members",
        "active_members", "revoked_members", "pending_requests", "open_invites",
        "referred_joins", "verified_members",
    ], [
        space.name, "request", False, 0, 0, 0, 0, 0, 0, 0,
    ]]


def test_member_activity_metrics_use_independent_current_state_and_range_counts():
    space = make_space("member-activity-metrics")
    manager = make_member("member-activity-manager", space)
    now = timezone.now()
    start, end = now - timedelta(days=2), now + timedelta(days=2)
    active = MakerspaceMembership.objects.get(user=manager, makerspace=space)
    active.activated_at = now
    active.verified_at = now
    active.save(update_fields=["activated_at", "verified_at"])
    MakerspaceMembership.objects.create(
        makerspace=space, user=make_user("member-activity-old"),
        activated_at=now - timedelta(days=10),
    )
    MakerspaceMembership.objects.create(
        makerspace=space, user=make_user("member-activity-revoked"), status="revoked",
        activated_at=now - timedelta(days=10), revoked_at=now,
    )
    MembershipRequest.objects.create(
        makerspace=space, kind=MembershipRequest.Kind.REQUEST,
        state=MembershipRequest.State.REQUESTED,
    )
    MembershipRequest.objects.create(
        makerspace=space, kind=MembershipRequest.Kind.INVITE,
        state=MembershipRequest.State.INVITED,
    )
    MembershipRequest.objects.create(
        makerspace=space, kind=MembershipRequest.Kind.INVITE,
        state=MembershipRequest.State.ACTIVE, auto_activate_on_claim=True, decided_at=now,
    )

    row = reports.report_data("member-activity", space.id, date_range=(start, end))["typed_rows"][0]

    assert row == {
        "makerspace_name": space.name, "membership_policy": "request", "referrals_enabled": False,
        "new_members": 1, "active_members": 2, "revoked_members": 1,
        "pending_requests": 1, "open_invites": 1, "referred_joins": 1,
        "verified_members": 1,
    }


def test_member_activity_range_is_start_inclusive_end_exclusive_for_current_timestamps():
    space = make_space("member-activity-range")
    start = timezone.now().replace(microsecond=0)
    end = start + timedelta(days=1)
    first = MakerspaceMembership.objects.create(
        makerspace=space, user=make_user("member-activity-range-start"), activated_at=start,
    )
    MakerspaceMembership.objects.create(
        makerspace=space, user=make_user("member-activity-range-end"), revoked_at=end,
    )
    MembershipRequest.objects.create(
        makerspace=space, kind=MembershipRequest.Kind.INVITE,
        state=MembershipRequest.State.ACTIVE, auto_activate_on_claim=True, decided_at=start,
    )
    MembershipRequest.objects.create(
        makerspace=space, kind=MembershipRequest.Kind.INVITE,
        state=MembershipRequest.State.ACTIVE, auto_activate_on_claim=True, decided_at=end,
    )

    row = reports.report_data("member-activity", space.id, date_range=(start, end))["typed_rows"][0]

    assert first.activated_at == start
    assert (row["new_members"], row["revoked_members"], row["referred_joins"]) == (1, 0, 1)


def test_member_activity_aggregate_excludes_ineligible_spaces_but_single_builder_keeps_exact_scope():
    eligible = make_space("member-activity-eligible")
    disabled = make_space("member-activity-disabled")
    disabled.enabled_modules.remove("reports")
    disabled.save(update_fields=["enabled_modules"])
    archived = make_space("member-activity-archived")
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    hidden = make_space("member-activity-hidden")
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])

    aggregate = reports.report_data("member-activity")["typed_rows"]

    assert {row["makerspace_id"] for row in aggregate} == {eligible.id}
    assert "makerspace_id" not in reports.report_data("member-activity", disabled.id)["typed_rows"][0]
    assert reports.report_data("member-activity", archived.id)["typed_rows"][0]["makerspace_name"] == archived.name


def test_member_activity_uses_one_scoped_query_without_join_multiplication():
    space = make_space("member-activity-query")
    for number in range(3):
        MakerspaceMembership.objects.create(
            makerspace=space, user=make_user(f"member-activity-query-member-{number}"),
        )
        MembershipRequest.objects.create(
            makerspace=space, kind=MembershipRequest.Kind.REQUEST,
            state=MembershipRequest.State.REQUESTED,
        )

    with CaptureQueriesContext(connection) as queries:
        row = reports.report_data("member-activity", space.id)["typed_rows"][0]

    assert len(queries) == 1
    assert (row["active_members"], row["pending_requests"]) == (3, 3)


def test_member_activity_api_is_scoped_and_generic_exports_keep_the_registered_shape():
    space = make_space("member-activity-api")
    manager = make_member("member-activity-api-manager", space)
    other = make_space("member-activity-api-other")
    superadmin = make_user(
        "member-activity-api-super", role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    client = authenticated_client(manager)

    response = client.get(f"/api/v1/admin/makerspace/{space.id}/analytics/member-activity")
    forbidden = client.get(f"/api/v1/admin/makerspace/{other.id}/analytics/member-activity")
    aggregate = authenticated_client(superadmin).get("/api/v1/admin/analytics/member-activity")

    assert response.status_code == 200
    assert response.data["rows"][0] == list(MEMBER_ACTIVITY_FIELDS)
    assert forbidden.status_code == 404
    assert {row["makerspace_id"] for row in aggregate.data["typed_rows"]} == {space.id, other.id}
    assert all("makerspace_id" not in row for row in response.data["typed_rows"])

    for fmt in ("csv", "xlsx"):
        per_space = client.get(
            f"/api/v1/admin/makerspace/{space.id}/reports/member-activity/export?format={fmt}"
        )
        aggregate_export = authenticated_client(superadmin).get(
            f"/api/v1/admin/reports/member-activity/export?format={fmt}"
        )
        assert per_space.status_code == aggregate_export.status_code == 200
        assert _header(per_space, fmt) == list(MEMBER_ACTIVITY_FIELDS)
        assert _header(aggregate_export, fmt) == ["makerspace_id", *MEMBER_ACTIVITY_FIELDS]


def _header(response, fmt):
    if fmt == "csv":
        return response.content.decode().splitlines()[0].split(",")
    return [cell.value for cell in load_workbook(BytesIO(response.content)).active[1]]
