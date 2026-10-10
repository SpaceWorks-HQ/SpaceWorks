from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

from apps.accounts.models import User
from apps.accounts.throttles_mfa import MFAChallengeThrottle, MFAUserThrottle
from tests.accounts.mfa_helpers import enrolled

pytestmark = pytest.mark.django_db


def rates(monkeypatch, scope):
    updated = {**SimpleRateThrottle.THROTTLE_RATES, scope: "1/hour"}
    monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", updated)
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", updated)


def challenge(user):
    response = APIClient().post("/api/v1/auth/login", {
        "username": user.username, "password": "Throttle password 394!", "surface": "member"}, format="json")
    assert response.status_code == 200
    return response.data["challenge"]


@pytest.mark.parametrize("scope", ["mfa_verify", "mfa_challenge", "mfa_user"])
def test_mfa_verification_throttles_ip_challenge_and_account(monkeypatch, scope):
    rates(monkeypatch, scope)
    user = User.objects.create_user(username="throttled-mfa", password="Throttle password 394!")
    enrolled(user)
    one, two = challenge(user), challenge(user)
    request = {"challenge": one, "code": "invalid"}
    client = APIClient()
    assert client.post("/api/v1/auth/mfa/verify", request, format="json").status_code == 401
    if scope == "mfa_user":
        request["challenge"] = two
        client = APIClient(REMOTE_ADDR="192.0.2.29")
    assert client.post("/api/v1/auth/mfa/verify", request, format="json").status_code == 429


def test_challenge_cache_key_never_contains_bearer():
    raw = "secret-bearer-that-must-not-appear-in-cache"
    key = MFAChallengeThrottle().get_cache_key(SimpleNamespace(data={"challenge": raw}), None)
    assert raw not in key


def test_invitation_accept_throttle_does_not_require_a_real_account(monkeypatch):
    rates(monkeypatch, "staff_invite_accept")
    payload = {"token": "x" * 43, "makerspace_slug": "missing", "password": "Throttle password 394!"}
    client = APIClient()
    assert client.post("/api/v1/auth/staff-invitations/accept", payload, format="json").status_code == 400
    assert client.post("/api/v1/auth/staff-invitations/accept", payload, format="json").status_code == 429


def test_mfa_management_and_invite_routes_declare_separate_budgets():
    from apps.accounts.views_mfa import MFARecoveryView, MFADisableView
    from apps.accounts.views_staff_invitations import StaffInvitationListView, StaffInvitationResendView
    assert MFARecoveryView.throttle_scope == MFADisableView.throttle_scope == "mfa_manage"
    assert StaffInvitationListView.throttle_scope == StaffInvitationResendView.throttle_scope == "staff_invite"
    assert MFAUserThrottle.scope != MFAChallengeThrottle.scope


@pytest.mark.parametrize("path", ["/api/v1/auth/login", "/api/v1/auth/mfa/enroll", "/api/v1/auth/mfa/verify"])
def test_non_mapping_json_body_is_a_validation_error(path):
    assert APIClient().post(path, ["bad-body"], format="json").status_code == 400
