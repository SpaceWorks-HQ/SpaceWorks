from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership
from tests.audit_explorer_helpers import (
    client_for,
    custom_role_member,
    member_with,
    org_auditor,
    space as audit_space,
    superadmin,
)
from tests.return_helpers import authenticated_client, make_space, make_user

pytestmark = pytest.mark.django_db

URL = "/api/v1/admin/audit-logs"
LEGACY_FIELDS = {
    "id", "actor", "action", "makerspace", "target_type", "target_id", "meta", "created_at",
}


def test_audit_log_endpoint_is_paginated_and_filters_still_apply():
    actor = make_user(
        "audit-superadmin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    space = make_space("audit-page")
    other_space = make_space("audit-other")
    for _ in range(25):
        audit.record(actor, "audit.page", makerspace=space, target=space)
    audit.record(actor, "audit.other", makerspace=other_space, target=other_space)

    client = authenticated_client(actor)
    page = client.get("/api/v1/admin/audit-logs")
    filtered = client.get(
        "/api/v1/admin/audit-logs",
        {
            "makerspace": space.id,
            "action": "audit.page",
            "target_type": "makerspaces.makerspace",
            "target_id": str(space.id),
        },
    )

    assert page.status_code == 200
    assert set(page.data) == {"count", "next", "previous", "results"}
    assert page.data["count"] == 26
    assert page.data["next"]
    assert len(page.data["results"]) == 24

    assert filtered.status_code == 200
    assert filtered.data["count"] == 25
    assert filtered.data["next"]
    assert {row["makerspace"] for row in filtered.data["results"]} == {space.id}
    assert {row["action"] for row in filtered.data["results"]} == {"audit.page"}
    assert {row["target_id"] for row in filtered.data["results"]} == {str(space.id)}


def test_raw_meta_never_leaves_the_list():
    root = superadmin("p10-root")
    space = audit_space("p10-meta")
    audit.record(
        root, "request.issued", makerspace=space, target=space,
        meta={"box_id": 4, "evidence_id": 7, "email": "x@example.com"},
    )
    audit.record(root, "never.heard_of", makerspace=space, target=space, meta={"phone": "1"})

    rows = {row["action"]: row for row in client_for(root).get(URL).data["results"]}

    issued, unknown = rows["request.issued"], rows["never.heard_of"]
    assert set(issued) == LEGACY_FIELDS | {
        "action_label", "actor_display", "meta_redacted", "target_link",
    }
    assert issued["meta"] == {"box_id": 4, "evidence_id": 7}
    assert issued["meta_redacted"] is True
    assert issued["action_label"] == "Request issued"
    assert issued["actor_display"] == "p10-root"
    assert issued["target_link"] is None
    assert unknown["meta"] == {} and unknown["meta_redacted"] is True
    assert unknown["action_label"] == "Unrecognized audit action"


def test_actor_and_date_filters_with_inclusive_start_exclusive_end():
    root = superadmin("p10-dates")
    other = superadmin("p10-dates-other")
    space = audit_space("p10-dates")
    early = audit.record(root, "audit.page", makerspace=space, target=space)
    late = audit.record(other, "audit.page", makerspace=space, target=space)
    early_at = AuditLog.objects.get(pk=early.pk).created_at
    late_at = AuditLog.objects.get(pk=late.pk).created_at
    client = client_for(root)

    by_actor = client.get(URL, {"actor": other.pk})
    # [early_at, late_at): the start is inclusive and the end exclusive.
    window = client.get(URL, {"start": early_at.isoformat(), "end": late_at.isoformat()})
    upto_late = client.get(
        URL, {"start": early_at.isoformat(), "end": (late_at + timedelta(microseconds=1)).isoformat()}
    )

    assert [row["id"] for row in by_actor.data["results"]] == [late.pk]
    if late_at > early_at:
        assert [row["id"] for row in window.data["results"]] == [early.pk]
    assert {row["id"] for row in upto_late.data["results"]} == {early.pk, late.pk}


@pytest.mark.parametrize(
    "params",
    [
        {"actor": "0"},
        {"actor": "abc"},
        {"makerspace": "-1"},
        {"start": "not-a-date"},
        {"start": "2026-01-01T00:00:00Z", "end": "2025-01-01T00:00:00Z"},
        {"start": "2024-01-01T00:00:00Z", "end": "2025-06-01T00:00:00Z"},
    ],
)
def test_invalid_filters_are_400(params):
    response = client_for(superadmin("p10-bad")).get(URL, params)
    assert response.status_code == 400


def test_inventory_manager_custom_role_and_organization_readers_are_scoped():
    space, other = audit_space("p10-scope"), audit_space("p10-scope-other")
    root = superadmin("p10-scope-root")
    mine = audit.record(root, "audit.page", makerspace=space, target=space)
    audit.record(root, "audit.page", makerspace=other, target=other)
    readers = [
        member_with(space, "p10-im", MakerspaceMembership.Role.INVENTORY_MANAGER),
        custom_role_member(space, "p10-custom", {rbac.Action.VIEW_AUDIT}),
        org_auditor(space, "p10-org"),
    ]
    for reader in readers:
        response = client_for(reader).get(URL)
        assert response.status_code == 200, reader.username
        ids = [row["id"] for row in response.data["results"]]
        assert ids == [mine.pk], reader.username
        # A valid out-of-scope makerspace filter is an empty page, not an error.
        assert client_for(reader).get(URL, {"makerspace": other.pk}).data["count"] == 0


def test_member_without_audit_action_sees_nothing():
    space = audit_space("p10-member")
    audit.record(superadmin("p10-member-root"), "audit.page", makerspace=space, target=space)
    member = custom_role_member(space, "p10-plain-member", set())
    response = client_for(member).get(URL)
    assert response.status_code == 403 or response.data["count"] == 0


def test_hidden_and_archived_makerspaces_do_not_leak_to_a_superadmin():
    root = superadmin("p10-hide-root")
    hidden, archived = audit_space("p10-hidden"), audit_space("p10-archived")
    audit.record(root, "audit.page", makerspace=hidden, target=hidden)
    audit.record(root, "audit.page", makerspace=archived, target=archived)
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    data = client_for(root).get(URL).data
    assert {row["makerspace"] for row in data["results"]}.isdisjoint({hidden.pk, archived.pk})
