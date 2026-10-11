"""D7: grants survive revocation and keep their originally stored expiry."""
import pytest
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied

from apps.machines.certifications import active_grant, require_certification_for_member
from apps.machines.models import CertificationGrant
from apps.makerspaces.models import MakerspaceMembership
from tests.machines.certification_helpers import _certification, _machine_type, _manager, _member, _space
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db


def test_grant_on_revoked_member_fails_closed_then_returns_on_reactivation_with_fixed_expiry():
    makerspace = _space("certification-membership-defaults")
    machine_type = _machine_type(makerspace)
    boss, _ = _manager(makerspace, "certification-default-manager", machine_type)
    person, row = _member(makerspace, "certification-default-member")
    kind = _certification(makerspace, machine_type, validity_days=30)
    response = authenticated_client(boss).post(reverse("admin-certification-type-grants", args=[kind.pk]), {"membership_id": row.pk}, format="json")
    assert response.status_code == 201, response.data
    grant = CertificationGrant.objects.get(pk=response.data["id"])
    expires_at = grant.expires_at
    assert expires_at is not None
    MakerspaceMembership.objects.filter(pk=row.pk).update(status="revoked")
    with pytest.raises(PermissionDenied):
        require_certification_for_member(makerspace, person, machine_type, purpose="booking")
    kind.validity_days = 1; kind.save(update_fields=["validity_days"])
    grant.refresh_from_db()
    assert grant.expires_at == expires_at
    MakerspaceMembership.objects.filter(pk=row.pk).update(status="active")
    require_certification_for_member(makerspace, person, machine_type, purpose="booking")
    assert active_grant(row, kind).pk == grant.pk
