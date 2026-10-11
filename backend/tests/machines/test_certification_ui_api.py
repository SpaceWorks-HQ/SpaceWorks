"""Member privacy, type-scoped administration and append-only renewals."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import PermissionDenied

from apps.audit.models import AuditLog
from apps.machines.certifications import require_certification
from apps.machines.models import CertificationGrant, MakerspaceMachineTypePolicy, Machine
from tests.machines.certification_helpers import _space, _machine_type, _manager, _member, _certification, _book, _bookable, _submit
from tests.module_helpers import disable_module
from tests.return_helpers import make_member

pytestmark = pytest.mark.django_db


def client(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def setup(slug):
    space = _space(slug)
    kind = _machine_type(space)
    manager, _ = _manager(space, slug + "-trainer", kind)
    member, membership = _member(space, slug + "-member")
    cert = _certification(space, kind, validity_days=30)
    return space, kind, manager, member, membership, cert


def test_member_history_only_contains_own_tenant_grants_and_no_staff_notes():
    space, _, _, member, membership, cert = setup("ui-own")
    _, other_membership = _member(space, "ui-other-member")
    own = CertificationGrant.objects.create(certification_type=cert, membership=membership, notes="Private trainer notes")
    CertificationGrant.objects.create(certification_type=cert, membership=other_membership)
    other, _, _, _, foreign_member, foreign_cert = setup("ui-foreign")
    CertificationGrant.objects.create(certification_type=foreign_cert, membership=foreign_member)
    api = client(member)
    response = api.get(reverse("member-certifications", args=[space.pk]))
    assert response.status_code == 200
    assert response.data["count"] == 1
    row = response.data["results"][0]
    assert row["id"] == own.pk and row["is_live"] is True
    assert {"notes", "membership", "granted_by", "member_name", "revoked_by"}.isdisjoint(row)
    assert api.get(reverse("member-certifications", args=[other.pk])).status_code == 403
    disable_module(space, "machines")
    assert api.get(reverse("member-certifications", args=[space.pk])).status_code == 400


def test_member_picker_and_renewal_are_machine_type_scoped():
    space, _, manager, _, membership, cert = setup("ui-renew")
    blocked, _ = _manager(space, "ui-unlinked-trainer")
    old = CertificationGrant.objects.create(certification_type=cert, membership=membership,
                                            expires_at=timezone.now() - timedelta(days=1), notes="Original evidence")
    old_expiry = old.expires_at
    for name in ("admin-certification-members", "admin-certification-type-grants"):
        assert client(blocked).get(reverse(name, args=[cert.pk])).status_code == 403
    denied = client(blocked).post(reverse("admin-certification-grant-renew", args=[old.pk]), {}, format="json")
    assert denied.status_code == 403
    members = client(manager).get(reverse("admin-certification-members", args=[cert.pk]))
    assert members.status_code == 200
    assert all(set(row) == {"id", "name"} for row in members.data["results"])
    renewed = client(manager).post(reverse("admin-certification-grant-renew", args=[old.pk]), {"notes": "Reassessed"}, format="json")
    assert renewed.status_code == 201, renewed.data
    old.refresh_from_db()
    assert old.expires_at == old_expiry and old.notes == "Original evidence"
    assert renewed.data["id"] != old.pk and renewed.data["is_live"] is True
    audit = AuditLog.objects.get(action="certification.renewed")
    assert audit.actor == manager and audit.meta["previous_grant_id"] == old.pk
    disable_module(space, "machines")
    assert client(manager).post(reverse("admin-certification-grant-renew", args=[old.pk]), {}, format="json").status_code == 400


def test_grant_rejects_foreign_inactive_members_and_past_expiry():
    space, _, manager, _, membership, cert = setup("ui-grant-boundary")
    _, _, _, _, foreign, _ = setup("ui-grant-foreign")
    url = reverse("admin-certification-type-grants", args=[cert.pk])
    api = client(manager)
    assert api.post(url, {"membership_id": foreign.pk}, format="json").status_code == 400
    assert api.post(url, {"membership_id": membership.pk, "expires_at": (timezone.now() - timedelta(days=1)).isoformat()}, format="json").status_code == 400
    membership.status = "revoked"
    membership.save(update_fields=["status"])
    assert api.post(url, {"membership_id": membership.pk}, format="json").status_code == 400
    assert not CertificationGrant.objects.filter(certification_type=cert).exists()


def test_revoke_preserves_original_training_notes():
    _, _, manager, _, membership, cert = setup("ui-revoke-notes")
    grant = CertificationGrant.objects.create(certification_type=cert, membership=membership, notes="Trained on SOP v1")
    result = client(manager).post(reverse("admin-certification-grant-revoke", args=[grant.pk]), {"notes": "Unsafe operation"}, format="json")
    assert result.status_code == 200
    grant.refresh_from_db()
    assert grant.notes == "Trained on SOP v1"
    assert AuditLog.objects.get(action="certification.revoked").meta["notes"] == "Unsafe operation"


def test_exact_expiry_blocks_booking_and_service_gate_like_a_missing_grant(monkeypatch):
    space, kind, _, member, membership, cert = setup("ui-expiry")
    moment = timezone.now()
    CertificationGrant.objects.create(certification_type=cert, membership=membership, expires_at=moment)
    monkeypatch.setattr(timezone, "now", lambda: moment)
    with pytest.raises(PermissionDenied):
        _book(_bookable(space, kind), member)
    with pytest.raises(PermissionDenied):
        require_certification(space, membership, kind, purpose="service")
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Laser")
    with pytest.raises(PermissionDenied):
        _submit(machine, member)


def test_policy_is_tenant_local_and_requires_space_manager_identity():
    from apps.accounts.rbac import Action
    space, kind, trainer, _, _, _ = setup("ui-policy")
    manager = make_member("ui-space-manager", space)
    delegate, _ = _manager(space, "ui-policy-delegate", actions=(Action.MANAGE_MAKERSPACE,))
    other, other_kind, _, _, _, _ = setup("ui-policy-other")
    path = reverse("admin-machine-type-policy", args=[space.pk, kind.pk])
    assert client(trainer).put(path, {"cert_reminder_days": 7}, format="json").status_code == 403
    assert client(delegate).put(path, {"cert_reminder_days": 7}, format="json").status_code == 403
    result = client(manager).put(path, {"cert_reminder_days": 7, "reminder_lead_days": 0, "grace_days": 2}, format="json")
    assert result.status_code == 200
    assert MakerspaceMachineTypePolicy.objects.get(makerspace=space).cert_reminder_days == 7
    assert AuditLog.objects.filter(action="machine_type.policy_updated", actor=manager).exists()
    assert client(manager).put(path, {"grace_days": -1}, format="json").status_code == 400
    assert client(manager).get(reverse("admin-machine-type-policy", args=[space.pk, other_kind.pk])).status_code == 404
    assert client(manager).get(reverse("admin-machine-type-policy", args=[other.pk, other_kind.pk])).status_code == 404


@pytest.mark.parametrize("surface", ["booking", "generic", "printer"])
def test_override_reason_reaches_boundary_serializers_but_cannot_authorize_member(surface):
    from apps.bookings.serializers_public import PublicBookingInputSerializer
    from apps.machines.public_service_serializers import PublicMachineServiceSubmitSerializer
    from apps.machines.public_printer_service_serializers import PublicPrinterSubmitSerializer
    space, kind, _, member, membership, _ = setup("ui-override-" + surface)
    now = timezone.now()
    classes = {"booking": PublicBookingInputSerializer, "generic": PublicMachineServiceSubmitSerializer,
               "printer": PublicPrinterSubmitSerializer}
    data = {"starts_at": now + timedelta(days=1), "ends_at": now + timedelta(days=1, hours=1)} if surface == "booking" else {"machine_id": 1, "title": "Work"}
    data["certification_override_reason"] = "I say I am trained"
    serializer = classes[surface](data=data)
    serializer.is_valid(raise_exception=True)
    assert serializer.validated_data["certification_override_reason"] == "I say I am trained"
    with pytest.raises(PermissionDenied):
        require_certification(space, membership, kind, purpose="booking" if surface == "booking" else "service",
                              actor=member, override_reason=serializer.validated_data["certification_override_reason"])
