import pytest

from apps.accounts import rbac
from apps.accounts.models import User
from apps.hardware_requests.models import ReplayCommand
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from tests.events.checkin_helpers import make_staff
from tests.hardware_requests.replay_helpers import envelope, execute, prepare, replay_env
from tests.hardware_requests.recovery_helpers import failed_issue, recovery_url, resolve, staff_client
from tests.hardware_requests.test_kiosk_online import kiosk_space

pytestmark = pytest.mark.django_db


def test_list_filters_paginate_and_do_not_return_channel_or_payload_secrets(replay_env, settings):
    env = replay_env
    one, two = failed_issue(env), failed_issue(env)
    client = staff_client(env.user)
    assert resolve(client, one).status_code == 200
    url = recovery_url("list", makerspace_id=env.space.pk)
    assert client.get(url).data["count"] == 1
    assert client.get(url, {"resolution": "resolved"}).data["results"][0]["id"] == str(one.pk)
    assert client.get(url, {"resolution": "all"}).data["count"] == 2
    assert client.get(url, {"resolution": "unknown"}).status_code == 400
    assert client.get(url, {"state": "prepared"}).status_code == 400
    data = client.get(recovery_url("detail", pk=two.pk)).data
    assert data["station_name"] == env.station.name and data["can_view_evidence"]
    assert not {"payload", "payload_fingerprint", "object_key", "pin", "public_token", "lease_token"} & set(data)


def test_cross_tenant_detail_resolve_and_origin_are_refused(replay_env):
    env = replay_env
    row = failed_issue(env)
    foreign = kiosk_space("recovery-foreign")
    client = staff_client(make_staff(foreign))
    assert client.get(recovery_url("list", makerspace_id=env.space.pk)).data["count"] == 0
    assert client.get(recovery_url("detail", pk=row.pk)).status_code == 404
    assert resolve(client, row).status_code == 404
    # Same user has authority, but a foreign tenant frontend must not route it.
    foreign.frontend_domain = "foreign.example.test"
    foreign.frontend_domain_status = "verified"
    foreign.save(update_fields=["frontend_domain", "frontend_domain_status"])
    own = staff_client(env.user)
    for name, kwargs in (("list", {"makerspace_id": env.space.pk}), ("detail", {"pk": row.pk})):
        assert own.get(recovery_url(name, **kwargs), HTTP_ORIGIN="https://foreign.example.test").status_code == 403
    assert own.post(recovery_url("resolve", pk=row.pk), {"resolution_code": "acknowledged_no_change"},
                    format="json", HTTP_ORIGIN="https://foreign.example.test").status_code == 403


def test_exact_custom_operation_scope_does_not_grant_evidence(replay_env):
    env = replay_env
    issue = failed_issue(env)
    assignment = envelope(env, payload={"request_id": env.request.pk, "box_code": "missing-box"})
    assert prepare(env, assignment).status_code == 200
    assert execute(env, assignment).status_code == 400
    role = MakerspaceRole.objects.create(makerspace=env.space, slug="issue-review", name="Issue review",
                                        granted_actions=[rbac.Action.ISSUE_REQUEST])
    member = MakerspaceMembership.objects.get(user=env.user, makerspace=env.space)
    member.role, member.assigned_role = "custom", role
    member.save()
    client = staff_client(env.user)
    data = client.get(recovery_url("list", makerspace_id=env.space.pk)).data
    assert data["count"] == 1 and data["results"][0]["id"] == str(issue.pk)
    assert not data["results"][0]["can_view_evidence"]
    assign_row = ReplayCommand.objects.get(client_command_id=assignment["client_command_id"])
    assert resolve(client, assign_row).status_code == 404
    assert client.get(f"/api/v1/admin/evidence/{issue.evidence_id}").status_code == 404


@pytest.mark.parametrize("change", ["suspended", "restricted", "membership", "password", "inactive"])
def test_revoked_current_authority_cannot_review(replay_env, change):
    env = replay_env
    row = failed_issue(env)
    if change == "membership":
        MakerspaceMembership.objects.filter(user=env.user).update(status="revoked")
    else:
        if change in ("suspended", "restricted"):
            env.user.access_status = change
        elif change == "password":
            env.user.must_change_password = True
        else:
            env.user.is_active = False
        env.user.save()
    response = resolve(staff_client(env.user), row)
    assert response.status_code in (403, 404)
    row.refresh_from_db()
    assert row.resolution_code is None


def test_historical_review_survives_kiosk_disable_and_hidden_superadmin_is_scoped(replay_env):
    env = replay_env
    row = failed_issue(env)
    env.space.enabled_features = [key for key in env.space.enabled_features if key != "inventory.kiosk"]
    env.space.superadmin_access_enabled = False
    env.space.save(update_fields=["enabled_features", "superadmin_access_enabled"])
    root = User.objects.create_user(username="recovery-root", role=User.Role.SUPERADMIN,
                                    access_status="active", is_superuser=True)
    client = staff_client(root)
    assert client.get(recovery_url("list", makerspace_id=env.space.pk)).data["count"] == 0
    assert resolve(client, row).status_code == 404
    assert resolve(staff_client(env.user), row).status_code == 200
