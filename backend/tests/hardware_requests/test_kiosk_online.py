"""Phase 9b online kiosk commands: exact policy, delegation and denial matrix."""

import pytest
from cryptography.fernet import Fernet
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.boxes.models import QrCode
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.kiosk_command_policy import (
    OPERATIONS,
    lease_actions,
    permitted_operations,
)
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from tests.events.checkin_helpers import make_space, make_staff
from tests.return_helpers import make_accepted_request, make_box, make_product

pytestmark = pytest.mark.django_db
ORIGIN = "http://localhost:5000"
HEADERS = {"HTTP_ORIGIN": ORIGIN, "HTTP_X_STATION_CSRF": "1"}


@pytest.fixture(autouse=True)
def kiosk_settings(settings):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode("ascii")
    settings.EVENT_STATION_PIN_PEPPER = "test-only-independent-station-pepper"
    settings.CORS_ALLOWED_ORIGINS = [ORIGIN]
    cache.clear()
    yield
    cache.clear()


def kiosk_space(slug="kiosk-online"):
    space = make_space(slug)
    space.enabled_features = [*space.enabled_features, "inventory.kiosk"]
    space.save(update_fields=["enabled_features"])
    return space


def leased(space, staff, kind="handover"):
    """Create a Station, open its session and take a lease as ``staff``."""
    admin = APIClient()
    admin.force_authenticate(staff)
    station = admin.post(
        reverse("admin-kiosk-station-list-create", kwargs={"makerspace_id": space.pk}),
        {"name": f"{kind}-desk", "kind": kind}, format="json",
    ).data
    token = station["public_token"]
    client = APIClient()
    client.post(
        reverse("kiosk-station-session", kwargs={"public_token": token}),
        {"pin": station["pin"]}, format="json", **HEADERS,
    )
    client.force_authenticate(staff)
    lease = client.post(
        reverse("kiosk-station-operator-lease", kwargs={"public_token": token}), **HEADERS
    )
    headers = {**HEADERS}
    if lease.status_code == 201:
        headers["HTTP_X_KIOSK_OPERATOR_LEASE"] = lease.data["lease_token"]
    return client, token, headers, station


def command(client, token, headers, kind, payload):
    return client.post(
        reverse("kiosk-station-command-online", kwargs={"public_token": token}),
        {"version": 1, "kind": kind, "payload": payload}, format="json", **headers,
    )


def test_policy_table_is_exact_and_never_offers_accept_reject_or_inventory_edit():
    assert set(OPERATIONS) == {
        "resolve_qr", "assign_box", "reviewed_issue", "reviewed_return",
        "direct_handout", "direct_return",
    }
    every = set().union(*(op.actions for op in OPERATIONS.values()))
    assert not every & {
        rbac.Action.ACCEPT_REQUEST, rbac.Action.REJECT_REQUEST,
        rbac.Action.EDIT_INVENTORY, rbac.Action.MANAGE_QR,
    }
    assert OPERATIONS["resolve_qr"].station_kinds == {"scanner", "handover"}
    assert all(
        op.station_kinds == {"handover"} for k, op in OPERATIONS.items() if k != "resolve_qr"
    )


def test_lease_actions_need_a_whole_operation_and_live_capabilities():
    space = kiosk_space()
    assert lease_actions(space, "handover", {rbac.Action.ISSUE_REQUEST}) == []
    full = lease_actions(space, "handover", {rbac.Action.ISSUE_REQUEST, rbac.Action.UPLOAD_EVIDENCE})
    assert set(full) == {rbac.Action.ISSUE_REQUEST, rbac.Action.UPLOAD_EVIDENCE}
    assert lease_actions(space, "scanner", {rbac.Action.ISSUE_REQUEST, rbac.Action.UPLOAD_EVIDENCE}) == []
    space.enabled_features = [k for k in space.enabled_features if k != "inventory.self_checkout"]
    space.save(update_fields=["enabled_features"])
    assert "direct_handout" not in permitted_operations(space, "handover")
    assert "reviewed_issue" in permitted_operations(space, "handover")


def test_resolve_qr_is_scoped_to_the_station_tenant_and_audited_as_the_user():
    space, other = kiosk_space(), kiosk_space("kiosk-other")
    staff = make_staff(space)
    client, token, headers, station = leased(space, staff, kind="scanner")
    product = make_product(space)
    qr = QrCode.objects.create(makerspace=space, target_type=QrCode.TargetType.PRODUCT, target_id=product.pk)
    foreign = QrCode.objects.create(
        makerspace=other, target_type=QrCode.TargetType.PRODUCT,
        target_id=make_product(other).pk,
    )
    ok = command(client, token, headers, "resolve_qr", {"payload": qr.payload})
    assert ok.status_code == 200, ok.data
    assert ok["Cache-Control"] == "private, no-store"
    assert command(client, token, headers, "resolve_qr", {"payload": foreign.payload}).status_code == 404
    log = AuditLog.objects.get(action="kiosk.online_command_executed")
    assert log.actor == staff
    assert log.meta["station_id"] == station["id"]
    assert log.meta["operation_kind"] == "resolve_qr"
    assert {"station_session_id", "station_version", "operator_lease_id"} <= set(log.meta)


def test_scanner_station_cannot_run_handover_commands():
    space = kiosk_space()
    staff = make_staff(space)
    client, token, headers, _ = leased(space, staff, kind="scanner")
    hardware_request = make_accepted_request(space, make_product(space), 1)
    box = make_box(space)
    response = command(client, token, headers, "assign_box",
                       {"request_id": hardware_request.pk, "box_code": box.code})
    assert response.status_code == 403
    hardware_request.refresh_from_db()
    assert hardware_request.assigned_box_id is None


def test_assign_box_delegates_to_the_workflow_and_derives_tenant_from_station():
    space, other = kiosk_space(), kiosk_space("kiosk-other2")
    staff = make_staff(space)
    client, token, headers, _ = leased(space, staff)
    hardware_request = make_accepted_request(space, make_product(space), 1)
    box = make_box(space)
    ok = command(client, token, headers, "assign_box",
                 {"request_id": hardware_request.pk, "box_code": box.code})
    assert ok.status_code == 200, ok.data
    hardware_request.refresh_from_db()
    assert hardware_request.assigned_box_id == box.pk
    assert AuditLog.objects.filter(action="kiosk.online_command_executed",
                                   meta__request_id=hardware_request.pk).exists()
    foreign = make_accepted_request(other, make_product(other), 1)
    assert command(client, token, headers, "assign_box",
                   {"request_id": foreign.pk, "box_code": box.code}).status_code == 404
    issue = command(client, token, headers, "reviewed_issue",
                    {"request_id": hardware_request.pk, "evidence_id": 999999, "remark": "x"})
    assert issue.status_code == 400
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.ACCEPTED


def test_unknown_kind_version_missing_lease_and_other_user_fail_closed():
    space = kiosk_space()
    staff = make_staff(space)
    client, token, headers, _ = leased(space, staff)
    url = reverse("kiosk-station-command-online", kwargs={"public_token": token})
    assert client.post(url, {"version": 1, "kind": "accept_request", "payload": {}},
                       format="json", **headers).status_code == 400
    assert client.post(url, {"version": 2, "kind": "resolve_qr", "payload": {"payload": "x"}},
                       format="json", **headers).status_code == 400
    assert command(client, token, HEADERS, "resolve_qr", {"payload": "x"}).status_code == 403
    intruder = make_staff(space, username="intruder")
    client.force_authenticate(intruder)
    assert command(client, token, headers, "resolve_qr", {"payload": "x"}).status_code == 403


def test_revoked_role_blocks_the_next_command_before_lease_expiry():
    space = kiosk_space()
    staff = make_staff(space)
    client, token, headers, _ = leased(space, staff)
    qr = QrCode.objects.create(makerspace=space, target_type=QrCode.TargetType.PRODUCT,
                               target_id=make_product(space).pk)
    assert command(client, token, headers, "resolve_qr", {"payload": qr.payload}).status_code == 200
    MakerspaceMembership.objects.filter(user=staff, makerspace=space).update(
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
    )
    assert command(client, token, headers, "resolve_qr", {"payload": qr.payload}).status_code == 403


def test_feature_off_answers_400_and_evidence_prepare_presigns_staging(monkeypatch):
    space = kiosk_space()
    staff = make_staff(space)
    client, token, headers, station = leased(space, staff)
    seen = {}

    def fake_presign(object_key, content_type):
        seen["key"] = object_key
        return {"url": "http://storage.test/upload", "fields": {"key": f"staging/{object_key}"}}

    monkeypatch.setattr("apps.evidence.services_upload.presigned_upload", fake_presign)
    url = reverse("kiosk-station-evidence-prepare", kwargs={"public_token": token})
    ok = client.post(url, {"evidence_type": "issue", "content_type": "image/jpeg"},
                     format="json", **headers)
    assert ok.status_code == 201, ok.data
    photo = EvidencePhoto.objects.get(pk=ok.data["evidence_id"])
    assert photo.uploaded_by == staff and photo.makerspace == space
    assert ok.data["fields"]["key"] == f"staging/{photo.object_key}"
    log = AuditLog.objects.get(action="kiosk.evidence_upload_issued")
    assert log.actor == staff and log.meta["evidence_id"] == photo.pk
    assert log.meta["station_id"] == station["id"]

    space.enabled_features = [k for k in space.enabled_features if k != "inventory.self_checkout"]
    space.save(update_fields=["enabled_features"])
    off = command(client, token, headers, "direct_return", {
        "loan_id": 1, "evidence_id": photo.pk, "notes": "n",
        "resolutions": [{"item_id": 1, "returned": 1}],
    })
    assert off.status_code == 400


def test_work_package_is_minimal_tenant_scoped_and_audited():
    space, other = kiosk_space(), kiosk_space("kiosk-wp-other")
    staff = make_staff(space)
    client, token, headers, station = leased(space, staff)
    hardware_request = make_accepted_request(space, make_product(space, name="Drill"), 2)
    url = reverse("kiosk-station-work-package", kwargs={"public_token": token})
    ok = client.post(url, {"kind": "reviewed_request", "id": hardware_request.pk}, format="json", **headers)
    assert ok.status_code == 200, ok.data
    assert ok["Cache-Control"] == "private, no-store"
    assert ok.data["status"] == "accepted"
    assert ok.data["lines"] == [{"item_id": hardware_request.items.get().pk, "label": "Drill", "quantity": 2, "returned": 0}]
    assert "requester_contact_email" not in ok.data
    log = AuditLog.objects.get(action="kiosk.work_package_issued")
    assert log.actor == staff and log.meta["request_id"] == hardware_request.pk
    assert log.meta["station_id"] == station["id"]
    foreign = make_accepted_request(other, make_product(other), 1)
    assert client.post(url, {"kind": "reviewed_request", "id": foreign.pk}, format="json", **headers).status_code == 404
    scanner_client, scanner_token, scanner_headers, _ = leased(space, staff, kind="scanner")
    scanner_url = reverse("kiosk-station-work-package", kwargs={"public_token": scanner_token})
    assert scanner_client.post(
        scanner_url, {"kind": "reviewed_request", "id": hardware_request.pk}, format="json", **scanner_headers
    ).status_code == 403


def test_prospective_direct_handout_package_requires_an_active_local_member():
    from tests.events.checkin_helpers import make_member

    space, other = kiosk_space(), kiosk_space("kiosk-dh-other")
    staff = make_staff(space)
    client, token, headers, _ = leased(space, staff)
    url = reverse("kiosk-station-work-package", kwargs={"public_token": token})
    member = make_member(space, display_name="Grace Hopper")
    ok = client.post(url, {"kind": "direct_handout", "id": member.pk}, format="json", **headers)
    assert ok.status_code == 200, ok.data
    assert ok.data["person_display"] == "Grace Hopper" and ok.data["status"] == "prospective"
    outsider = make_member(other, username="outsider")
    response = client.post(url, {"kind": "direct_handout", "id": outsider.pk}, format="json", **headers)
    assert response.status_code == 403
