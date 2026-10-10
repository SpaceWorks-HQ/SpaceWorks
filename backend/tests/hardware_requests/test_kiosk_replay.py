from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.boxes.models import BoxScan
from apps.hardware_requests.models import HardwareRequest, ReplayCommand
from apps.hardware_requests.replay_fingerprint import fingerprint
from apps.hardware_requests.workflow_errors import DepositRequired
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from tests.events.checkin_helpers import make_member
from tests.hardware_requests.replay_helpers import envelope, execute, prepare, replay_env, validated
from tests.return_helpers import make_accepted_request, make_product

pytestmark = pytest.mark.django_db


def test_prepare_and_execute_duplicate_apply_exactly_one_box_scan_without_login(replay_env):
    env = replay_env
    data = envelope(env)
    first, again = prepare(env, data), prepare(env, data)
    assert first.status_code == again.status_code == 200
    assert first.data["replay_id"] == again.data["replay_id"]
    assert ReplayCommand.objects.count() == 1
    one, two = execute(env, data), execute(env, data)
    assert one.status_code == two.status_code == 200
    assert one.data == two.data
    assert one.data["result_request_id"] == env.request.pk
    assert BoxScan.objects.filter(request=env.request).count() == 1
    log = AuditLog.objects.get(action="kiosk.replay_succeeded")
    assert log.actor == env.user and log.meta["operator_lease_id"] == str(env.lease.pk)
    assert one["Cache-Control"] == "private, no-store"


def test_canonical_objects_ignore_key_order_and_lists_preserve_order(replay_env):
    data = envelope(replay_env, "direct_handout", {"borrower_id": 1, "qr_payloads": ["a", "b"]})
    value = validated(data)
    reversed_keys = dict(reversed(list(data.items())))
    assert fingerprint(value) == fingerprint(validated(reversed_keys))
    reversed_keys["payload"] = {"qr_payloads": ["b", "a"], "borrower_id": 1}
    assert fingerprint(value) != fingerprint(validated(reversed_keys))


def test_changed_payload_and_stream_position_conflict_without_mutating_original(replay_env):
    env = replay_env
    data = envelope(env)
    assert prepare(env, data).status_code == 200
    changed = deepcopy(data)
    changed["payload"]["box_code"] = "another-box"
    assert prepare(env, changed).data["code"] == "idempotency_conflict"
    assert execute(env, changed).data["code"] == "idempotency_conflict"
    position = {**data, "client_command_id": str(uuid4())}
    assert prepare(env, position).status_code == 409
    assert ReplayCommand.objects.get().state == "prepared"


@pytest.mark.parametrize("minutes,code", [(-481, "command_expired"), (6, "clock_skew")])
def test_command_age_is_enforced_at_prepare(replay_env, minutes, code):
    data = envelope(replay_env, client_created_at=(timezone.now() + timedelta(minutes=minutes)).isoformat())
    response = prepare(replay_env, data)
    assert response.data["code"] == code and not ReplayCommand.objects.exists()


@pytest.mark.parametrize("change,code", [
    ({"version": 2}, "unsupported_operation_version"),
    ({"kind": "resolve_qr"}, "unsupported_operation_version"),
    ({"makerspace_id": 999}, "invalid_command"),
    ({"sequence": 2}, "predecessor_missing"),
])
def test_unknown_protocol_and_untrusted_tenant_are_refused(replay_env, change, code):
    response = prepare(replay_env, envelope(replay_env, **change))
    assert response.data["code"] == code


def test_predecessor_pending_failed_and_cross_aggregate_refusals(replay_env):
    env = replay_env
    first = envelope(env)
    assert prepare(env, first).status_code == 200
    second = envelope(env, "reviewed_issue", {"request_id": env.request.pk},
                      aggregate_id=first["aggregate_id"], sequence=2,
                      predecessor_client_id=first["client_command_id"])
    assert prepare(env, second).status_code == 200
    assert execute(env, second).data["code"] == "predecessor_pending"
    assert ReplayCommand.objects.get(client_command_id=second["client_command_id"]).state == "prepared"
    wrong = {**second, "client_command_id": str(uuid4()), "aggregate_id": str(uuid4())}
    assert prepare(env, wrong).data["code"] == "predecessor_missing"
    from apps.hardware_requests import workflow
    from tests.return_helpers import make_issue_evidence
    # Another live handover moves accepted -> issued before this queued assign.
    workflow.assign_box(env.user, env.request, env.box.code)
    workflow.issue_request(env.user, env.request, make_issue_evidence(env.space, env.user).pk)
    assert execute(env, first).data["code"] == "request_state_changed"
    assert execute(env, second).data["code"] == "predecessor_failed"


@pytest.mark.parametrize("revoke,code", [
    ("station", "station_revoked"), ("lease", "lease_expired"),
    ("user", "permission_revoked"), ("password", "permission_revoked"),
    ("membership", "permission_revoked"), ("action", "permission_revoked"),
    ("feature", "feature_disabled"), ("session", "session_mismatch"),
])
def test_live_revocation_prevents_domain_effect(replay_env, revoke, code):
    env = replay_env
    data = envelope(env)
    assert prepare(env, data).status_code == 200
    if revoke == "station":
        env.credential.is_enabled = False
        env.credential.save(update_fields=["is_enabled"])
    elif revoke == "lease":
        env.lease.revoked_at = timezone.now()
        env.lease.save(update_fields=["revoked_at"])
    elif revoke in {"user", "password"}:
        User.objects.filter(pk=env.user.pk).update(**({"access_status": "suspended"} if revoke == "user" else {"must_change_password": True}))
    elif revoke in {"membership", "action"}:
        membership = MakerspaceMembership.objects.get(user=env.user, makerspace=env.space)
        if revoke == "membership":
            membership.status = "revoked"
        else:
            membership.role = "custom"
            membership.assigned_role = MakerspaceRole.objects.get(makerspace=env.space, slug="member")
        membership.save()
    elif revoke == "session":
        from apps.makerspaces.models_station_leases import StationSessionRevocation
        StationSessionRevocation.objects.create(session_id=env.lease.station_session_id,
                                               station=env.station, expires_at=env.lease.expires_at)
    else:
        env.space.enabled_features = [key for key in env.space.enabled_features if key != "inventory.kiosk"]
        env.space.save(update_fields=["enabled_features"])
    response = execute(env, data)
    assert response.data["code"] == code
    assert not BoxScan.objects.filter(request=env.request).exists()


def test_issue_deposit_and_box_scan_failures_are_typed_and_terminal(replay_env, monkeypatch):
    env = replay_env
    data = envelope(env, "reviewed_issue", {"request_id": env.request.pk})
    assert prepare(env, data).status_code == 200
    def unpaid(*args):
        raise DepositRequired(SimpleNamespace(pk=1))
    with monkeypatch.context() as patch:
        patch.setattr("apps.hardware_requests.loan_payments.require_deposit_settled", unpaid)
        response = execute(env, data)
    assert response.data["code"] == "deposit_unsettled"
    assert ReplayCommand.objects.get().state == "failed"
    another = envelope(env, "reviewed_issue", {"request_id": env.request.pk})
    assert prepare(env, another).status_code == 200
    assert execute(env, another).data["code"] == "box_scan_required"
    env.request.refresh_from_db()
    assert env.request.status == "accepted"


def test_reviewed_issue_and_return_commit_with_replay_results(replay_env):
    env = replay_env
    assigned = envelope(env)
    assert prepare(env, assigned).status_code == execute(env, assigned).status_code == 200
    issued = envelope(env, "reviewed_issue", {"request_id": env.request.pk, "remark": "Photo at handover"},
                      aggregate_id=assigned["aggregate_id"], sequence=2, predecessor_client_id=assigned["client_command_id"])
    assert prepare(env, issued).status_code == execute(env, issued).status_code == 200
    returned = envelope(env, "reviewed_return", {"request_id": env.request.pk, "box_code": env.box.code,
                        "remark": "All returned", "resolutions": [{"item_id": env.request.items.get().pk, "returned": 1}]},
                        aggregate_id=assigned["aggregate_id"], sequence=3, predecessor_client_id=issued["client_command_id"])
    assert prepare(env, returned).status_code == 200
    response = execute(env, returned)
    assert response.status_code == 200, response.data
    assert response.data["result_return_event_id"] is not None
    env.request.refresh_from_db()
    assert env.request.status == "returned"


def test_chained_direct_return_resolves_created_container_loan(replay_env, monkeypatch):
    env = replay_env
    borrower = make_member(env.space)
    monkeypatch.setattr("apps.hardware_requests.direct_loan_workflow.require_active_member_presence", lambda *args: SimpleNamespace(membership=None))
    handout = envelope(env, "direct_handout", {"borrower_id": borrower.pk, "container_id": env.box.pk})
    returned = envelope(env, "direct_return", {"notes": "Empty vessel returned", "resolutions": []},
                        aggregate_id=handout["aggregate_id"], sequence=2, predecessor_client_id=handout["client_command_id"])
    assert prepare(env, handout).status_code == prepare(env, returned).status_code == 200
    issued = execute(env, handout)
    assert issued.status_code == 200, issued.data
    response = execute(env, returned)
    assert response.status_code == 200, response.data
    assert response.data["result_loan_id"] == issued.data["result_loan_id"]


def test_tenant_reference_and_model_identity_guards(replay_env):
    env = replay_env
    from tests.hardware_requests.test_kiosk_online import kiosk_space
    other = kiosk_space("replay-other")
    foreign = make_accepted_request(other, make_product(other), 1)
    assert prepare(env, envelope(env, payload={"request_id": foreign.pk, "box_code": env.box.code})).data["code"] == "target_missing"
    assert prepare(env, envelope(env)).status_code == 200
    command = ReplayCommand.objects.get()
    command.makerspace = other
    with pytest.raises(ValidationError):
        command.save()
    command.refresh_from_db()
    command.payload_fingerprint = "0" * 64
    with pytest.raises(ValidationError):
        command.save()
    with pytest.raises(IntegrityError), transaction.atomic():
        ReplayCommand.objects.filter(pk=command.pk).update(state="claimed")


def test_module_off_and_missing_cookie_origin_csrf_or_lease_fail_closed(replay_env, monkeypatch):
    from django.urls import reverse
    env = replay_env
    data = envelope(env)
    url = reverse("kiosk-replay-prepare", kwargs={"public_token": env.credential.public_token})
    for header in env.headers:
        headers = {key: value for key, value in env.headers.items() if key != header}
        assert env.client.post(url, data, format="json", **headers).status_code == 403
    cookie = env.client.cookies.pop("sw_kiosk_station")
    assert prepare(env, data).status_code == 403
    env.client.cookies["sw_kiosk_station"] = cookie
    from apps.makerspaces.platform import module_enabled
    monkeypatch.setattr("apps.hardware_requests.replay_authorization.module_enabled",
                        lambda space, key: key != "request_workflow" and module_enabled(space, key))
    response = prepare(env, data)
    assert response.status_code == 400 and response.data["code"] == "module_disabled"


def test_permission_is_checked_again_after_s3_and_before_domain_commit(replay_env, monkeypatch):
    from apps.evidence.storage import finalize_upload
    env = replay_env
    data = envelope(env, "reviewed_issue", {"request_id": env.request.pk})
    assert prepare(env, data).status_code == 200
    def revoke_after_upload(photo, limit):
        result = finalize_upload(photo, limit)
        User.objects.filter(pk=env.user.pk).update(must_change_password=True)
        return result
    monkeypatch.setattr("apps.evidence.storage.finalize_upload", revoke_after_upload)
    response = execute(env, data)
    assert response.data["code"] == "permission_revoked"
    assert ReplayCommand.objects.get().state == "failed"
    env.request.refresh_from_db()
    assert env.request.status == "accepted"


def test_current_presence_and_inventory_refusals_are_typed(replay_env, monkeypatch):
    env = replay_env
    borrower = make_member(env.space)
    data = envelope(env, "direct_handout", {"borrower_id": borrower.pk,
                                           "items": [{"product_id": env.product.pk, "quantity": 1}]})
    assert prepare(env, data).status_code == 200
    assert execute(env, data).data["code"] == "presence_expired"
    monkeypatch.setattr("apps.hardware_requests.direct_loan_workflow.require_active_member_presence", lambda *args: SimpleNamespace(membership=None))
    from apps.inventory import availability
    env.product.refresh_from_db()
    availability.issue_available(env.product, env.product.available_quantity)
    another = envelope(env, "direct_handout", data["payload"])
    assert prepare(env, another).status_code == 200
    assert execute(env, another).data["code"] == "inventory_unavailable"


def test_source_gate_refuses_prepare_and_execute_without_mutation(replay_env):
    from tests.tenant_migration.source_gate_helpers import close_gate, make_actor
    env = replay_env
    data = envelope(env)
    assert prepare(env, data).status_code == 200
    close_gate(env.space, make_actor())
    assert prepare(env, envelope(env)).status_code == 423
    assert execute(env, data).status_code == 423
    assert ReplayCommand.objects.get().state == "prepared"
    assert not BoxScan.objects.exists()


def test_current_box_mismatch_is_a_terminal_return_failure(replay_env):
    env = replay_env
    assigned = envelope(env)
    assert prepare(env, assigned).status_code == execute(env, assigned).status_code == 200
    issued = envelope(env, "reviewed_issue", {"request_id": env.request.pk})
    assert prepare(env, issued).status_code == execute(env, issued).status_code == 200
    data = envelope(env, "reviewed_return", {"request_id": env.request.pk, "box_code": "wrong-box",
                    "remark": "Return photo", "resolutions": [{"item_id": env.request.items.get().pk, "returned": 1}]})
    assert prepare(env, data).status_code == 200
    assert execute(env, data).data["code"] == "box_mismatch"
    env.request.refresh_from_db()
    assert env.request.status == "issued"


def test_a_different_lease_cannot_take_over_an_owned_command(replay_env):
    from apps.makerspaces.station_operator_leases import issue_lease
    env = replay_env
    data = envelope(env)
    assert prepare(env, data).status_code == 200
    _lease, token = issue_lease(station=env.station, credential=env.credential,
                               session_id=env.lease.station_session_id,
                               session_expires_at=env.lease.expires_at, user=env.user)
    env.headers["HTTP_X_KIOSK_OPERATOR_LEASE"] = token
    assert execute(env, data).data["code"] == "session_mismatch"
    assert ReplayCommand.objects.get().state == "prepared"
