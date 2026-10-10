"""M1/M7: HTTP certification enforcement and the public consumable allowlist."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.machines.models import CertificationGrant, Machine, MachineServiceRequest
from apps.presence import services as presence
from tests.events.checkin_helpers import client_for
from tests.machines import certification_helpers as cert
from tests.machines.test_consumable_public_eligibility import _public_pool_setup

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("grant_state", ["missing", "live", "expired", "revoked", "feature_off"])
def test_public_machine_submit_enforces_certification_at_http_boundary(grant_state):
    space = cert._space(
        f"combo-http-cert-{grant_state}", certifications=grant_state != "feature_off",
    )
    machine_type = cert._machine_type(space)
    certification = cert._certification(space, machine_type, name="Laser induction")
    member, membership = cert._member(space, f"combo-http-cert-{grant_state}-member")
    presence.start_session(member, space, 60)
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Laser 1",
    )
    if grant_state in ("live", "expired", "revoked"):
        grant_fields = {}
        if grant_state == "expired":
            grant_fields["expires_at"] = timezone.now() - timedelta(days=1)
        elif grant_state == "revoked":
            grant_fields["revoked_at"] = timezone.now() - timedelta(hours=1)
        CertificationGrant.objects.create(
            certification_type=certification, membership=membership, **grant_fields,
        )

    response = client_for(member).post(
        reverse("public-machine-service-request-submit", args=[space.slug]),
        {"machine_id": machine.pk, "title": "Cut a panel"},
        format="json",
    )

    rows = MachineServiceRequest.objects.filter(makerspace=space)
    audits = AuditLog.objects.filter(makerspace=space, action="machine_service.submitted")
    if grant_state in ("live", "feature_off"):
        assert response.status_code == 201, response.data
        job = rows.get()
        assert str(job.public_token) == str(response.data["public_token"])
        assert job.member_id == member.pk
        assert job.status == MachineServiceRequest.Status.PENDING
        assert audits.get().actor_id == member.pk
    else:
        assert response.status_code == 403, response.data
        assert response.data["code"] == "certification_required"
        assert response.data["certifications"] == ["Laser induction"]
        assert not rows.exists()
        assert not audits.exists()


def test_public_printer_pools_expose_only_id_material_and_color():
    """M7: quantity, price and internal machine references never reach the public."""
    space, _queue, _excluded, included = _public_pool_setup("combo-pool-fields")

    response = APIClient().get(reverse("public-printer-service-pools", args=[space.slug]))

    assert response.status_code == 200, response.data
    assert {row["id"] for row in response.data} == {pool.pk for pool in included}
    expected = {pool.pk: pool for pool in included}
    for row in response.data:
        assert set(row) == {"id", "material", "color"}
        assert row == {
            "id": row["id"], "material": expected[row["id"]].material,
            "color": expected[row["id"]].color,
        }
