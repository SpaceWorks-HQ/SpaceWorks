from unittest.mock import Mock

import pytest

from apps.accounts.models import User
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import (
    authenticated_client,
    make_issued_request,
    make_member,
    make_product,
    make_return_evidence,
    make_space,
    make_user,
    return_payload,
    return_url,
)
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def test_guest_admin_can_return_and_cross_tenant_returns_404(monkeypatch):
    makerspace = make_space("return-perms")
    other_space = make_space("return-perms-other")
    guest_admin = make_handout_member("return-perms-guest", makerspace)
    owner_admin = make_member("return-perms-owner", makerspace)
    other_admin = make_member("return-perms-other-admin", other_space)
    product = make_product(makerspace)
    hardware_request = make_issued_request(makerspace, owner_admin, [(product, 1)])
    evidence = make_return_evidence(makerspace, owner_admin)
    object_exists = Mock(return_value=True)
    monkeypatch.setattr("apps.evidence.storage.object_exists", object_exists)

    guest = authenticated_client(guest_admin).post(
        return_url(hardware_request),
        return_payload(hardware_request, evidence),
        format="json",
    )
    cross_tenant = authenticated_client(other_admin).post(
        return_url(hardware_request),
        return_payload(hardware_request, evidence),
        format="json",
    )

    assert guest.status_code == 200
    assert cross_tenant.status_code == 404
    assert object_exists.call_count == 1


def test_superadmin_can_return_without_membership(monkeypatch):
    makerspace = make_space("return-superadmin")
    admin = make_member("return-superadmin-admin", makerspace)
    superadmin = make_user(
        "return-superadmin-user",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    product = make_product(makerspace)
    hardware_request = make_issued_request(makerspace, admin, [(product, 1)])
    evidence = make_return_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))

    response = authenticated_client(superadmin).post(
        return_url(hardware_request),
        return_payload(hardware_request, evidence),
        format="json",
    )

    assert response.status_code == 200
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.RETURNED
