"""Staff API for certification types and grants: scoping, soft-delete, audit."""

import pytest
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.machines.models import CertificationGrant, CertificationType
from tests.machines.certification_helpers import (
    _bookable,
    _book,
    _certification,
    _machine_type,
    _manager,
    _member,
    _space,
)

pytestmark = pytest.mark.django_db


def _client(actor):
    client = APIClient()
    client.force_authenticate(user=actor)
    return client


def test_staff_api_creates_grants_and_revokes_with_audit():
    space = _space("cert-api")
    machine_type = _machine_type(space)
    manager, _role = _manager(space, "cert-api-mgr", machine_type)
    member, membership = _member(space, "cert-api-member")
    client = _client(manager)

    created = client.post(
        reverse("admin-certification-types", args=[space.pk]),
        {
            "machine_type": machine_type.pk,
            "name": "Laser induction",
            "validity_days": 30,
            "is_required_for_booking": True,
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    type_id = created.data["id"]

    listed = client.get(reverse("admin-certification-types", args=[space.pk]))
    assert [row["id"] for row in listed.data] == [type_id]

    granted = client.post(
        reverse("admin-certification-type-grants", args=[type_id]),
        {"membership_id": membership.pk, "notes": "Trained"},
        format="json",
    )
    assert granted.status_code == 201, granted.data
    assert granted.data["is_live"] is True
    # validity_days seeded the expiry rather than leaving it open-ended.
    assert granted.data["expires_at"] is not None

    assert _book(_bookable(space, machine_type), member).pk is not None

    revoked = client.post(
        reverse("admin-certification-grant-revoke", args=[granted.data["id"]]),
        {"notes": "Failed reassessment"},
        format="json",
    )
    assert revoked.status_code == 200, revoked.data
    assert revoked.data["is_live"] is False

    with pytest.raises(PermissionDenied):
        _book(_bookable(space, machine_type), member)

    actions = set(
        AuditLog.objects.filter(makerspace=space).values_list("action", flat=True)
    )
    assert {"certification_type.created", "certification.granted", "certification.revoked"} <= actions


def test_staff_api_deactivate_is_a_soft_delete():
    space = _space("cert-api-delete")
    machine_type = _machine_type(space)
    manager, _role = _manager(space, "cert-api-del-mgr", machine_type)
    certification = _certification(space, machine_type)
    _member(space, "cert-api-del-member")

    response = _client(manager).delete(
        reverse("admin-certification-type-detail", args=[certification.pk])
    )

    assert response.status_code == 200
    certification.refresh_from_db()
    assert certification.is_active is False
    assert CertificationType.objects.filter(pk=certification.pk).exists()
    assert AuditLog.objects.filter(action="certification_type.deactivated").exists()


def test_staff_api_hides_and_refuses_types_for_unlinked_machine_types():
    space = _space("cert-api-scope")
    laser = _machine_type(space, "Laser")
    printer = _machine_type(space, "Printer")
    laser_certification = _certification(space, laser, name="Laser induction")
    _certification(space, printer, name="Printer induction")
    manager, _role = _manager(space, "cert-api-scope-mgr", laser)
    client = _client(manager)

    listed = client.get(reverse("admin-certification-types", args=[space.pk]))
    assert [row["id"] for row in listed.data] == [laser_certification.pk]

    refused = client.patch(
        reverse(
            "admin-certification-type-detail",
            args=[CertificationType.objects.get(name="Printer induction").pk],
        ),
        {"name": "Renamed"},
        format="json",
    )
    assert refused.status_code == 403


def test_staff_api_refuses_a_membership_from_another_makerspace():
    space = _space("cert-api-tenant")
    other = _space("cert-api-tenant-other")
    machine_type = _machine_type(space)
    certification = _certification(space, machine_type)
    manager, _role = _manager(space, "cert-api-tenant-mgr", machine_type)
    _outsider, foreign_membership = _member(other, "cert-api-tenant-outsider")

    response = _client(manager).post(
        reverse("admin-certification-type-grants", args=[certification.pk]),
        {"membership_id": foreign_membership.pk},
        format="json",
    )

    assert response.status_code == 400
    assert not CertificationGrant.objects.exists()
