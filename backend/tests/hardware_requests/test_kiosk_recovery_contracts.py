from types import SimpleNamespace

import pytest
from django.urls import reverse

from apps.boxes.models import QrCode, QrScanEvent
from apps.hardware_requests.models import PublicToolLoan, ReplayCommand, ReturnEvent
from apps.hardware_requests.replay_recovery_policy import subject_context
from tests.events.checkin_helpers import make_member
from tests.hardware_requests.replay_helpers import envelope, execute, prepare, replay_env
from tests.hardware_requests.recovery_helpers import resolve, staff_client

pytestmark = pytest.mark.django_db


def test_work_package_advertises_actual_configured_replay_limit(replay_env, settings):
    env = replay_env
    settings.KIOSK_COMMAND_MAX_AGE_SECONDS = 12345
    env.client.force_authenticate(env.user)
    response = env.client.post(reverse("kiosk-station-work-package", kwargs={
        "public_token": env.credential.public_token,
    }), {"kind": "reviewed_request", "id": env.request.pk}, format="json", **env.headers)
    assert response.status_code == 200, response.data
    assert response.data["command_age_limit_seconds"] == 12345


def test_revoked_stored_qr_cannot_return_direct_loan_or_commit_return_effects(replay_env, monkeypatch):
    env = replay_env
    borrower = make_member(env.space)
    monkeypatch.setattr("apps.hardware_requests.direct_loan_workflow.require_active_member_presence", lambda *args: SimpleNamespace(membership=None))
    qr = QrCode.objects.create(makerspace=env.space, target_type=QrCode.TargetType.PRODUCT, target_id=env.product.pk)
    handout = envelope(env, "direct_handout", {"borrower_id": borrower.pk, "qr_payloads": [qr.payload]})
    assert prepare(env, handout).status_code == 200
    issued = execute(env, handout)
    assert issued.status_code == 200, issued.data
    loan = PublicToolLoan.objects.get(pk=issued.data["result_loan_id"])
    QrCode.objects.filter(pk=qr.pk).update(status=QrCode.Status.REVOKED)
    returned = envelope(env, "direct_return", {"loan_id": issued.data["result_loan_id"], "notes": "Return photo",
                                              "qr_payload": qr.payload, "resolutions": [
                                                  {"item_id": loan.request.items.get().pk, "returned": 1}]})
    assert prepare(env, returned).status_code == 200
    response = execute(env, returned)
    assert response.status_code == 409 and response.data["code"] == "qr_revoked"
    command = ReplayCommand.objects.get(client_command_id=returned["client_command_id"])
    assert command.state == "failed" and command.evidence_id
    command.subject_loan.refresh_from_db()
    assert command.subject_loan.status == "checked_out"
    assert not ReturnEvent.objects.filter(request_id=issued.data["result_request_id"]).exists()
    assert not QrScanEvent.objects.filter(request_id=issued.data["result_request_id"], context="return").exists()


def test_chained_failed_return_derives_subject_and_links_explicit_fresh_return(replay_env, monkeypatch):
    env = replay_env
    borrower = make_member(env.space)
    monkeypatch.setattr("apps.hardware_requests.direct_loan_workflow.require_active_member_presence", lambda *args: SimpleNamespace(membership=None))
    handout = envelope(env, "direct_handout", {"borrower_id": borrower.pk, "container_id": env.box.pk})
    assert prepare(env, handout).status_code == 200
    issued = execute(env, handout)
    assert issued.status_code == 200
    returning = envelope(env, "direct_return", {"notes": "Wrong QR at return", "qr_payload": "invalid-qr", "resolutions": []},
                         aggregate_id=handout["aggregate_id"], sequence=2, predecessor_client_id=handout["client_command_id"])
    assert prepare(env, returning).status_code == 200
    assert execute(env, returning).data["code"] == "qr_revoked"
    failed = ReplayCommand.objects.get(client_command_id=returning["client_command_id"])
    assert failed.subject_loan_id is None
    assert subject_context(failed) == (None, issued.data["result_loan_id"])
    correction = envelope(env, "direct_return", {"loan_id": issued.data["result_loan_id"], "notes": "Checked physical return", "resolutions": []})
    assert prepare(env, correction).status_code == execute(env, correction).status_code == 200
    replacement = ReplayCommand.objects.get(client_command_id=correction["client_command_id"])
    assert resolve(staff_client(env.user), failed, "replaced_online", replacement).status_code == 200


def test_failed_direct_handout_without_identity_cannot_link_arbitrary_success(replay_env, monkeypatch):
    env = replay_env
    borrower = make_member(env.space)
    handout = envelope(env, "direct_handout", {"borrower_id": borrower.pk, "container_id": env.box.pk})
    assert prepare(env, handout).status_code == 200
    assert execute(env, handout).data["code"] == "presence_expired"
    failed = ReplayCommand.objects.get(client_command_id=handout["client_command_id"])
    monkeypatch.setattr("apps.hardware_requests.direct_loan_workflow.require_active_member_presence", lambda *args: SimpleNamespace(membership=None))
    correction = envelope(env, "direct_handout", handout["payload"])
    assert prepare(env, correction).status_code == execute(env, correction).status_code == 200
    replacement = ReplayCommand.objects.get(client_command_id=correction["client_command_id"])
    assert resolve(staff_client(env.user), failed, "replaced_online", replacement).status_code == 409


def test_resolution_registries_and_catalog_snapshot_are_complete(replay_env):
    from apps.data_export.references_core import RELATIONAL_USER_FIELDS
    from apps.makerspaces.origin_scope_model_lookups import BASE_MODEL_LOOKUPS
    from apps.makerspaces.origin_scope_routes import MAKERSPACE_KWARG_ROUTES
    from apps.tenant_migration.audit_references_meta_kiosk import KIOSK_AUDIT_EDGES
    from apps.tenant_migration.audit_references_targets import AuditReferenceDisposition as D
    from apps.tenant_migration.tenant_dump_catalog import CATALOG_SCHEMA_SHA256, schema_digest
    from apps.tenant_migration.tenant_dump_authority import AUTHORITY_FIELD_OVERRIDES
    from apps.tenant_migration.tenant_dump_types import AuthorityDisposition
    assert ("hardware_requests.ReplayCommand", "resolved_by") in RELATIONAL_USER_FIELDS
    for field in ("resolution_code", "resolved_by", "resolved_at", "replacement_command"):
        rule = AUTHORITY_FIELD_OVERRIDES[("hardware_requests.ReplayCommand", field)]
        assert rule.dispositions == (AuthorityDisposition.DROP,)
    assert schema_digest() == CATALOG_SCHEMA_SHA256
    assert MAKERSPACE_KWARG_ROUTES["admin-kiosk-replay-list"] == "makerspace_id"
    assert BASE_MODEL_LOOKUPS["admin-kiosk-replay-resolve"] == ("hardware_requests.ReplayCommand", "makerspace_id")
    for field in ("replay_id", "replacement_replay_id"):
        assert KIOSK_AUDIT_EDGES[("kiosk.replay_resolved", field)].disposition == D.SOURCE_LOCAL_SNAPSHOT
