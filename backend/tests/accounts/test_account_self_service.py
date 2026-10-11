"""Own identity/session mutations, including JWT lineage after refresh rotation."""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models_devices import DeviceGrant, NativeAppRegistration
from apps.accounts.serializers import SpaceWorksTokenRefreshSerializer
from apps.accounts.tokens import SpaceWorksRefreshToken
from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from tests.return_helpers import make_space, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def account():
    space = make_space("account-self-service")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"member_accounts", "membership"})
    space.enabled_features = sorted(set(space.enabled_features) | {"membership.self_service"})
    space.save()
    user = make_user("account-owner", access_status="active")
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    membership = MakerspaceMembership.objects.create(user=user, makerspace=space,
                                                    assigned_role=role, role="custom")
    token = SpaceWorksRefreshToken.for_user(user)
    token["surface"] = "member"
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    return user, space, membership, token, client


def base(space):
    return f"/api/v1/member/makerspaces/{space.pk}/account"


def test_member_edits_contact_fields_and_audits_names_only(account):
    user, space, _, _, client = account
    response = client.patch(f"{base(space)}/profile", {
        "display_name": "New name", "first_name": "First", "last_name": "Last",
        "phone": "shared landline",
    }, format="json")
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.display_name == "New name" and user.phone == "shared landline"
    assert user.phone_e164 == ""
    event = AuditLog.objects.get(action="account.profile_updated", actor=user)
    assert event.meta == {"fields": ["display_name", "first_name", "last_name", "phone"]}


@pytest.mark.parametrize("field", ["email", "phone_e164", "role", "is_active", "password"])
def test_profile_refuses_identity_and_authority_fields(account, field):
    _, space, _, _, client = account
    assert client.patch(f"{base(space)}/profile", {field: "changed"}, format="json").status_code == 400


@pytest.mark.parametrize("payload", [[], [{"display_name": "bad shape"}], "bad shape"])
def test_profile_rejects_non_object_payload(account, payload):
    _, space, _, _, client = account
    assert client.patch(f"{base(space)}/profile", payload, format="json").status_code == 400


def test_session_list_is_paginated_owned_and_marks_current(account):
    user, space, _, token, client = account
    other = make_user("other-session-owner", access_status="active")
    other_token = SpaceWorksRefreshToken.for_user(other)
    second = SpaceWorksRefreshToken.for_user(user)
    response = client.get(f"{base(space)}/sessions")
    assert response.status_code == 200
    assert response.data["count"] == 2
    rows = response.data["results"]
    own_id = f"web:{token['sid'].removeprefix('session:')}"
    other_id = f"web:{other_token['sid'].removeprefix('session:')}"
    assert any(row["id"] == own_id and row["current"] for row in rows)
    assert not any(row["id"] == other_id for row in rows)
    assert any(row["id"] == f"web:{second['sid'].removeprefix('session:')}" for row in rows)


def test_rotation_preserves_session_and_revoke_invalidates_access_and_refresh(account):
    _, space, _, original, client = account
    serializer = SpaceWorksTokenRefreshSerializer(data={"refresh": str(original)})
    serializer.is_valid(raise_exception=True)
    renewed = SpaceWorksRefreshToken(serializer.validated_data["refresh"])
    assert renewed["sid"] == original["sid"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {renewed.access_token}")
    session_id = f"web:{renewed['sid'].removeprefix('session:')}"
    assert client.delete(f"{base(space)}/sessions/{session_id}").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    from rest_framework.exceptions import AuthenticationFailed
    with pytest.raises(AuthenticationFailed) as exc:
        data = SpaceWorksTokenRefreshSerializer(data={"refresh": str(renewed)})
        data.is_valid(raise_exception=True)
    assert "revoked" in str(exc.value)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {original.access_token}")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_cannot_revoke_another_users_web_session(account):
    _, space, _, _, client = account
    other = make_user("foreign-session", access_status="active")
    token = SpaceWorksRefreshToken.for_user(other)
    identifier = f"web:{token['sid'].removeprefix('session:')}"
    assert client.delete(f"{base(space)}/sessions/{identifier}").status_code == 404
    foreign_client = APIClient()
    foreign_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    assert foreign_client.get("/api/v1/auth/me").status_code == 200


def test_legacy_refresh_is_listed_revoked_or_adopted_on_next_refresh(account):
    from rest_framework_simplejwt.exceptions import TokenError
    user, space, _, _, client = account
    legacy = SpaceWorksRefreshToken.for_user(user, web_session=False)
    identifier = f"web-legacy:{legacy['jti']}"
    response = client.get(f"{base(space)}/sessions")
    assert any(row["id"] == identifier for row in response.data["results"])
    assert client.delete(f"{base(space)}/sessions/{identifier}").status_code == 204
    with pytest.raises(TokenError):
        SpaceWorksRefreshToken(str(legacy))
    next_legacy = SpaceWorksRefreshToken.for_user(user, web_session=False)
    serializer = SpaceWorksTokenRefreshSerializer(data={"refresh": str(next_legacy)})
    serializer.is_valid(raise_exception=True)
    assert SpaceWorksRefreshToken(serializer.validated_data["refresh"]).get("sid")


def test_device_revoke_is_owned_and_preserves_other_grants(account):
    user, space, _, _, client = account
    registration = NativeAppRegistration.objects.create(
        makerspace=space, platform="android", app_id="test.app", environment="production",
        verifier_config_key="test-verifier", status="approved",
    )
    other = make_user("foreign-device-owner", access_status="active")
    def grant(owner):
        return DeviceGrant.objects.create(user=owner, registration=registration,
            platform="android", app_id="test.app", environment="production",
            signing_identity="signer", attestation_subject_fingerprint="hash",
            attested_at=timezone.now(), last_used_at=timezone.now())
    own, foreign = grant(user), grant(other)
    assert client.delete(f"{base(space)}/sessions/device:{foreign.pk}").status_code == 404
    assert client.delete(f"{base(space)}/sessions/device:{own.pk}").status_code == 204
    own.refresh_from_db()
    foreign.refresh_from_db()
    assert own.status == "revoked" and foreign.status == "active"


@pytest.mark.parametrize("module", ["membership", "member_accounts"])
def test_account_routes_answer_400_with_module_off(account, module):
    _, space, _, _, client = account
    space.enabled_modules = [item for item in space.enabled_modules if item != module]
    space.save(update_fields=["enabled_modules"])
    assert client.get(f"{base(space)}/profile").status_code == 400
    assert client.get(f"{base(space)}/sessions").status_code == 400


def test_account_feature_off_and_cross_tenant(account):
    _, space, _, _, client = account
    foreign = make_space("account-foreign-space")
    assert client.get(f"{base(foreign)}/profile").status_code == 404
    space.enabled_features = [item for item in space.enabled_features if item != "membership.self_service"]
    space.save(update_fields=["enabled_features"])
    assert client.get(f"{base(space)}/profile").status_code == 400


def test_mfa_session_marker_does_not_bypass_credential_version(account):
    from apps.accounts.mfa_policy import stamp
    from tests.accounts.mfa_helpers import enrolled
    user, space, _, _, client = account
    credential, _ = enrolled(user)
    stamp(user, credential)
    token = SpaceWorksRefreshToken.for_user(user)
    token["surface"] = "member"
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    assert client.get(f"{base(space)}/sessions").status_code == 200
    import uuid
    credential.version = uuid.uuid4()
    credential.save(update_fields=["version"])
    assert client.get(f"{base(space)}/sessions").status_code == 401
