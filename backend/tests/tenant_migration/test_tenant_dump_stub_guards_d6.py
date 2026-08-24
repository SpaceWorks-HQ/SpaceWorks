import pytest
from django.contrib.auth import authenticate
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import PasswordResetEnvelope, User
from apps.accounts.services_password_reset import request_password_reset
from apps.accounts.services_password_reset_drain import (
    claim_pending_envelopes,
    prepare_delivery,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.handout_roles import make_handout_member


pytestmark = pytest.mark.django_db


def _edited_stub(username="edited-stub"):
    user = User.objects.create_user(
        username=username,
        is_tenant_dump_stub=True,
        is_active=False,
        access_status=User.AccessStatus.SUSPENDED,
    )
    # Simulate an operator editing every field that used to imply a usable account.
    user.email = f"{username}@example.test"
    user.set_password("Edited stub password 419!")
    user.is_active = True
    user.access_status = User.AccessStatus.ACTIVE
    user.is_staff = True
    user.is_superuser = True
    user.role = User.Role.SUPERADMIN
    user.save()
    return user


def test_password_authentication_refuses_stub_after_security_fields_are_edited():
    user = _edited_stub("stub-password-login")

    assert authenticate(
        username=user.username, password="Edited stub password 419!"
    ) is None

    response = APIClient().post(
        reverse("auth-login"),
        {"username": user.username, "password": "Edited stub password 419!"},
        format="json",
    )

    assert response.status_code == 401
    assert "access" not in response.data


def test_password_reset_drain_refuses_stub_after_contact_and_status_are_edited():
    user = _edited_stub("stub-password-reset")
    request_password_reset(user.email)
    claim = claim_pending_envelopes(owner="tenant-dump-stub-test")[0]

    outcome = prepare_delivery(claim)

    assert outcome == "discarded"
    envelope = PasswordResetEnvelope.objects.get(pk=claim.envelope_id)
    assert envelope.user_id is None
    assert envelope.digest_is_live is False


def test_member_claim_path_refuses_stub_even_when_it_looks_like_a_walk_in():
    space = Makerspace.objects.create(name="Stub claim", slug="stub-claim")
    issuer = make_handout_member("stub-claim-issuer", space)
    target = User(
        username="stub-claim-target",
        is_tenant_dump_stub=True,
        is_walk_in=True,
        is_active=True,
        access_status=User.AccessStatus.ACTIVE,
    )
    target.set_unusable_password()
    target.save()
    membership = MakerspaceMembership.objects.create(
        makerspace=space,
        user=target,
        role=MakerspaceMembership.Role.CUSTOM,
    )
    client = APIClient()
    client.force_authenticate(issuer)

    response = client.post(
        f"/api/v1/admin/makerspaces/{space.pk}/member-claim-codes",
        {"membership_id": membership.pk},
        format="json",
    )

    assert response.status_code == 409


def test_rbac_refuses_stub_even_after_global_and_membership_grants_are_added():
    space = Makerspace.objects.create(name="Stub RBAC", slug="stub-rbac")
    user = _edited_stub("stub-rbac-user")
    MakerspaceMembership.objects.create(makerspace=space, user=user)

    assert rbac.resolve_scope(user) == set()
    assert rbac.makerspaces_for_action(user, rbac.Action.MANAGE_MAKERSPACE) == set()
    assert rbac.effective_actions(user, space.pk) == set()
    assert rbac.can(user, rbac.Action.MANAGE_MAKERSPACE, space.pk) is False
