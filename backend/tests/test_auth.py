import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces.models import Makerspace, MakerspaceMembership

pytestmark = pytest.mark.django_db
LOGIN = "/api/v1/auth/login"


@pytest.fixture(autouse=True)
def _allow_test_origin(settings):
    # The container env sets CORS_ALLOWED_ORIGINS without :5000; pin it here so the
    # CSRF Origin check is deterministic regardless of deployment env. Reject-origin
    # tests still reject (evil/look-alike origins are not in this list).
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:5000"]


def make_staff(username="boss", role=User.Role.SPACE_MANAGER, password="pw-strong-123", **kw):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@e.com", password=password, role=role, **kw
    )


def test_login_returns_access_and_sets_refresh_cookie():
    user = make_staff()
    s = Makerspace.objects.create(name="Lab", slug="lab")
    MakerspaceMembership.objects.create(user=user, makerspace=s, role="space_manager")
    client = APIClient()

    resp = client.post(LOGIN, {"username": "boss", "password": "pw-strong-123"}, format="json")

    assert resp.status_code == 200
    assert "access" in resp.data
    assert "refresh" not in resp.data  # refresh lives in the cookie, never the body
    assert resp.data["user"]["role"] == "space_manager"
    assert resp.data["user"]["makerspaces"][0]["slug"] == "lab"
    assert "refresh_token" in resp.cookies
    assert resp.cookies["refresh_token"]["httponly"] is True
    audit = AuditLog.objects.get(action="auth.login_succeeded")
    assert audit.actor == user
    assert audit.target_id == str(user.id)
    assert "boss" not in str(audit.meta)


def test_login_rejects_bad_password():
    make_staff()
    resp = APIClient().post(LOGIN, {"username": "boss", "password": "wrong"}, format="json")
    assert resp.status_code == 401
    audit = AuditLog.objects.get(action="auth.login_failed")
    assert audit.actor is None
    assert "boss" not in str(audit.meta)
    assert "wrong" not in str(audit.meta)


def test_login_rejects_suspended_account():
    make_staff(username="bad", access_status=User.AccessStatus.SUSPENDED)
    resp = APIClient().post(LOGIN, {"username": "bad", "password": "pw-strong-123"}, format="json")
    assert resp.status_code in (401, 403)


REFRESH = "/api/v1/auth/refresh"
ALLOWED_ORIGIN = "http://localhost:5000"  # in CORS_ALLOWED_ORIGINS default


def _login(client, username="boss"):
    make_staff(username=username)
    return client.post(LOGIN, {"username": username, "password": "pw-strong-123"}, format="json")


def _csrf_headers():
    # Header presence forces CORS preflight; Origin must be allowlisted.
    return {"HTTP_X_REFRESH_CSRF": "1", "HTTP_ORIGIN": ALLOWED_ORIGIN}


def test_refresh_rejected_without_csrf_header():
    client = APIClient()
    _login(client)
    resp = client.post(REFRESH, HTTP_ORIGIN=ALLOWED_ORIGIN)  # header missing
    assert resp.status_code == 403
    assert AuditLog.objects.filter(
        action="auth.refresh_rejected", meta__reason="csrf"
    ).exists()


def test_refresh_rejected_from_unknown_origin():
    client = APIClient()
    _login(client)
    resp = client.post(REFRESH, HTTP_X_REFRESH_CSRF="1", HTTP_ORIGIN="https://evil.test")
    assert resp.status_code == 403


def test_refresh_rejected_on_origin_prefix_bypass():
    # Exact-match guard: a look-alike host must not pass (re-review fix).
    client = APIClient()
    _login(client)
    resp = client.post(
        REFRESH, HTTP_X_REFRESH_CSRF="1", HTTP_ORIGIN="http://localhost:5000.evil.test"
    )
    assert resp.status_code == 403


def test_refresh_allows_registered_staff_frontend_origin():
    registered_origin = "https://staff.example"
    Makerspace.objects.create(
        name="Registered",
        slug="registered",
        frontend_domain="staff.example",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )
    client = APIClient()
    _login(client)

    resp = client.post(
        REFRESH,
        HTTP_X_REFRESH_CSRF="1",
        HTTP_ORIGIN=registered_origin,
    )

    assert resp.status_code == 200
    assert "access" in resp.data
    assert "refresh_token" in resp.cookies


def test_refresh_rejects_non_localhost_http_staff_frontend_origin():
    Makerspace.objects.create(
        name="HTTP Staff",
        slug="http-staff",
        frontend_domain="staff.example",
        frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
    )
    client = APIClient()
    _login(client)

    rejected = client.post(
        REFRESH,
        HTTP_X_REFRESH_CSRF="1",
        HTTP_ORIGIN="http://staff.example",
    )
    accepted = client.post(
        REFRESH,
        HTTP_X_REFRESH_CSRF="1",
        HTTP_ORIGIN="https://staff.example",
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 200


def test_refresh_rejects_origin_only_in_cors_allowed_origins():
    """A public/API-client origin must not pass the refresh CSRF check."""
    api_origin = "https://api-client.example"
    Makerspace.objects.create(
        name="Public", slug="public-origins", cors_allowed_origins=[api_origin]
    )
    client = APIClient()
    _login(client)

    resp = client.post(REFRESH, HTTP_X_REFRESH_CSRF="1", HTTP_ORIGIN=api_origin)

    assert resp.status_code == 403


def test_refresh_rejects_unregistered_origin_with_csrf_header():
    Makerspace.objects.create(name="Registered", slug="registered-origin-reject")
    client = APIClient()
    _login(client)

    resp = client.post(
        REFRESH,
        HTTP_X_REFRESH_CSRF="1",
        HTTP_ORIGIN="https://unregistered.example",
    )

    assert resp.status_code == 403


def test_refresh_rotates_and_returns_new_access():
    client = APIClient()
    _login(client)
    old_refresh = client.cookies["refresh_token"].value
    resp = client.post(REFRESH, **_csrf_headers())
    assert resp.status_code == 200
    assert "access" in resp.data
    assert "refresh_token" in resp.cookies  # rotated
    assert resp.cookies["refresh_token"].value != old_refresh


def test_old_refresh_rejected_after_rotation():
    client = APIClient()
    _login(client)
    old_refresh = client.cookies["refresh_token"].value
    assert client.post(REFRESH, **_csrf_headers()).status_code == 200  # rotates
    # Replay the OLD token - blacklist-after-rotation must reject it (review fix #6).
    replay = APIClient()
    replay.cookies["refresh_token"] = old_refresh
    resp = replay.post(REFRESH, **_csrf_headers())
    assert resp.status_code == 401


LOGOUT = "/api/v1/auth/logout"


def test_logout_clears_cookie_and_blocks_reuse():
    client = APIClient()
    _login(client)
    old_refresh = client.cookies["refresh_token"].value
    out = client.post(LOGOUT, **_csrf_headers())
    assert out.status_code == 200
    assert client.cookies["refresh_token"].value == ""  # cookie cleared
    assert AuditLog.objects.filter(action="auth.logout").exists()

    # The blacklisted refresh token must no longer work (review fix #6).
    replay = APIClient()
    replay.cookies["refresh_token"] = old_refresh
    resp = replay.post(REFRESH, **_csrf_headers())
    assert resp.status_code == 401


def test_logout_rejected_without_csrf_header():
    client = APIClient()
    _login(client)
    resp = client.post(LOGOUT, HTTP_ORIGIN=ALLOWED_ORIGIN)  # header missing
    assert resp.status_code == 403


ME = "/api/v1/auth/me"


def test_me_requires_auth_and_returns_profile():
    client = APIClient()
    assert client.get(ME).status_code == 401
    login = _login(client, username="meuser")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    resp = client.get(ME)
    assert resp.status_code == 200
    assert resp.data["username"] == "meuser"
    assert resp.data["role"] == "space_manager"


# --- Part A / Task A2b: staff refresh CSRF trusts the auto-verified self-host origin ---


@pytest.mark.django_db
def test_refresh_trusts_autoverified_selfhost_custom_origin(settings):
    from django.test import override_settings
    from apps.makerspaces import domain_verification

    with override_settings(PLATFORM_DOMAIN_SUFFIX=""):
        makerspace = Makerspace.objects.create(
            name="Self Host", slug="selfhost-refresh", frontend_domain="tools.selfhost.example"
        )
        # A1/A2: self-host auto-trust marks the domain VERIFIED without a TXT challenge.
        status, _at, _detail = domain_verification.verify_domain(makerspace)
        assert status == Makerspace.DomainStatus.VERIFIED

        client = APIClient()
        _login(client)

        # Origin is NOT in CORS_ALLOWED_ORIGINS; it must pass purely via the verified
        # staff-origin allowlist (staff_origin_is_registered).
        resp = client.post(
            REFRESH,
            HTTP_X_REFRESH_CSRF="1",
            HTTP_ORIGIN="https://tools.selfhost.example",
        )

    assert resp.status_code == 200
    assert "access" in resp.data
    assert "refresh_token" in resp.cookies
