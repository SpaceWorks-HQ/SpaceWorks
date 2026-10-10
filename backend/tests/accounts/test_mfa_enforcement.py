import pytest
from cryptography.fernet import Fernet
from django.test import Client
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIClient

from apps.accounts.mfa_crypto import totp
from apps.accounts.mfa_policy import required
from apps.accounts.mfa_recovery import reset_superadmin_mfa
from apps.accounts.models import User
from apps.accounts.models_mfa import MFAChallenge, UserMFA
from apps.accounts.tokens import SpaceWorksRefreshToken
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.accounts.mfa_helpers import complete_enrollment, enrolled

pytestmark = pytest.mark.django_db
PASSWORD = "Staff enforcement password 984!"


@pytest.fixture(autouse=True)
def encryption(settings):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode()
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:5000"]


def person(name, **fields):
    return User.objects.create_user(username=name, password=PASSWORD, **fields)


def space_with_staff():
    space = Makerspace.objects.create(name="MFA staff", slug="mfa-staff")
    staff = person("space-staff")
    MakerspaceMembership.objects.create(user=staff, makerspace=space, role="inventory_manager")
    return space, staff


def require_staff(space):
    space.enabled_features = [*space.enabled_features, "security.staff_mfa_required"]
    space.save(update_fields=["enabled_features"])


def test_superadmin_cannot_mint_tokens_without_enrollment_even_on_member_surface():
    root = person("root-without-mfa", role=User.Role.SUPERADMIN)
    with pytest.raises(AuthenticationFailed):
        SpaceWorksRefreshToken.for_user(root)
    response = APIClient().post("/api/v1/auth/login", {
        "username": root.username, "password": PASSWORD, "surface": "member"}, format="json")
    assert response.status_code == 200 and response.data["enrollment_required"]
    assert "access" not in response.data


def test_space_policy_invalidates_prior_access_and_refresh_but_not_member_sessions():
    space, staff = space_with_staff()
    member = person("community-member")
    MakerspaceMembership.objects.create(user=member, makerspace=space, role="member")
    refresh = SpaceWorksRefreshToken.for_user(staff)
    refresh["surface"] = "staff_api"
    access = str(refresh.access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    assert client.get("/api/v1/auth/me").status_code == 200
    require_staff(space)
    assert required(staff) and not required(member)
    assert client.get("/api/v1/auth/me").status_code == 401
    client.credentials()
    client.cookies["refresh_token"] = str(refresh)
    assert client.post("/api/v1/auth/refresh", HTTP_X_REFRESH_CSRF="1",
                       HTTP_ORIGIN="http://localhost:5000").status_code == 401
    for user in (staff, member):
        response = client.post("/api/v1/auth/login", {
            "username": user.username, "password": PASSWORD, "surface": "member"}, format="json")
        assert response.status_code == 200
        assert bool(response.data.get("enrollment_required")) == (user == staff)


def test_staff_policy_covers_organization_authority():
    from apps.organizations.models import Organization, OrganizationMakerspace, OrganizationMembership
    from apps.accounts.rbac import Action
    space = Makerspace.objects.create(name="Organization MFA", slug="org-mfa")
    require_staff(space)
    org = Organization.objects.create(name="MFA Org", slug="mfa-org")
    OrganizationMakerspace.objects.create(organization=org, makerspace=space, relationship="owner")
    actor = person("org-staff")
    OrganizationMembership.objects.create(organization=org, user=actor,
                                           granted_actions=[Action.VIEW_INVENTORY])
    assert required(actor)


def test_required_staff_cannot_disable_mfa():
    space, staff = space_with_staff()
    require_staff(space)
    client = APIClient()
    first = client.post("/api/v1/auth/login", {"username": staff.username, "password": PASSWORD}, format="json")
    completed = complete_enrollment(client, first)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {completed.data['access']}")
    assert client.post("/api/v1/auth/mfa/disable", {"password": PASSWORD}, format="json").status_code == 403
    assert UserMFA.objects.get(user=staff).enabled_at


def test_staff_authority_is_rechecked_at_challenge_completion():
    space, staff = space_with_staff()
    _, secret = enrolled(staff)
    client = APIClient()
    first = client.post("/api/v1/auth/login", {"username": staff.username, "password": PASSWORD}, format="json")
    MakerspaceMembership.objects.filter(user=staff, makerspace=space).update(status="revoked")
    response = client.post("/api/v1/auth/mfa/verify", {"challenge": first.data["challenge"],
        "code": totp(secret, int(timezone.now().timestamp() // 30))}, format="json")
    assert response.status_code == 403 and "access" not in response.data


def test_control_password_session_cannot_reach_admin_until_mfa_and_recovers_safely():
    root = User.objects.create_superuser(username="control-mfa-root", password=PASSWORD)
    client = Client()
    client.force_login(root)
    assert client.get("/control/").url == "/mfa/control/"
    setup = client.get("/mfa/control/")
    assert setup.status_code == 200
    secret = setup.context["secret"]
    completed = client.post("/mfa/control/", {"code": totp(secret, int(timezone.now().timestamp() // 30))})
    assert completed.status_code == 200 and len(completed.context["recovery_codes"]) == 10
    assert client.get("/control/").status_code == 200
    reset_superadmin_mfa(root)
    assert client.get("/control/").url == "/mfa/control/"
    assert not UserMFA.objects.get(user=root).enabled_at


def test_control_challenge_cannot_be_consumed_on_api():
    root = User.objects.create_superuser(username="control-bound-root", password=PASSWORD)
    client = Client()
    client.force_login(root)
    setup = client.get("/mfa/control/")
    code = totp(setup.context["secret"], int(timezone.now().timestamp() // 30))
    raw = client.session["mfa_challenge"]
    assert APIClient().post("/api/v1/auth/mfa/confirm", {"challenge": raw, "code": code},
                            format="json").status_code == 401
    assert MFAChallenge.objects.get().consumed_at is None


def test_global_mfa_enrollment_remains_available_when_staff_tenant_is_frozen():
    from tests.tenant_migration.source_gate_helpers import close_gate
    space, staff = space_with_staff()
    require_staff(space)
    space.frontend_domain = "frozen-mfa.example.test"
    space.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    space.save(update_fields=["frontend_domain", "frontend_domain_status"])
    close_gate(space, staff)
    client = APIClient()
    origin = "https://frozen-mfa.example.test"
    first = client.post("/api/v1/auth/login", {"username": staff.username, "password": PASSWORD,
        "surface": "staff"}, format="json", HTTP_ORIGIN=origin)
    assert first.status_code == 200 and first.data["enrollment_required"]
    assert complete_enrollment(client, first, HTTP_ORIGIN=origin).data["access"]
