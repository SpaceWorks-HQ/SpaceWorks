from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from cryptography.fernet import Fernet
from django.db import close_old_connections, transaction
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import AuthenticationFailed

from apps.accounts.mfa_crypto import totp
from apps.accounts.models import User
from apps.accounts.models_mfa import UserMFA
from apps.accounts.tokens import SpaceWorksRefreshToken
from tests.accounts.mfa_helpers import enrolled

pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_challenges_cannot_consume_the_same_totp_step(settings):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode()
    user = User.objects.create_user(username="concurrent-mfa", password="Concurrency password 553!")
    row, secret = enrolled(user)
    raw = []
    for _ in range(2):
        response = APIClient().post("/api/v1/auth/login", {
            "username": user.username, "password": "Concurrency password 553!", "surface": "member"},
            format="json")
        assert response.status_code == 200
        raw.append(response.data["challenge"])
    code = totp(secret, int(timezone.now().timestamp() // 30))
    barrier = Barrier(2)

    def verify(token):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return APIClient().post("/api/v1/auth/mfa/verify", {"challenge": token, "code": code}, format="json")
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(verify, raw))
    assert sorted(response.status_code for response in responses) == [200, 401]
    assert UserMFA.objects.get(pk=row.pk).last_step >= 0


def test_token_minting_waits_for_enrollment_and_cannot_adopt_an_unproven_version(settings):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode()
    user = User.objects.create_user(username="mint-enrollment-race", password="Concurrency password 553!")
    started, finished = Event(), Event()

    def mint():
        close_old_connections()
        started.set()
        try:
            SpaceWorksRefreshToken.for_user(user)
            return "minted"
        except AuthenticationFailed:
            return "refused"
        finally:
            finished.set()
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            User.objects.select_for_update().get(pk=user.pk)
            future = pool.submit(mint)
            assert started.wait(timeout=5)
            assert not finished.wait(timeout=1), "Token issuance must share the credential-change lock"
            enrolled(user)
        assert future.result(timeout=10) == "refused"
