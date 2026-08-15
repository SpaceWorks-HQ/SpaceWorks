import queue
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.db import close_old_connections, connection, transaction
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.accounts.services_password_reset import confirm_password_reset
from tests.accounts.password_reset_helpers import issue_otp

pytestmark = pytest.mark.django_db(transaction=True)

OTP_PASSWORD = "Recovered-by-otp-771!"


def make_user(label):
    return User.objects.create_user(
        username=label,
        email=f"{label}@example.org",
        password="Starting-password-419!",
        access_status=User.AccessStatus.ACTIVE,
    )


def test_legacy_link_waiting_behind_otp_rechecks_the_locked_user(monkeypatch):
    user = make_user("race-link-otp")
    code = issue_otp(user, monkeypatch)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    pid_queue = queue.Queue()

    def submit_legacy():
        return _thread_post(
            pid_queue,
            reverse("auth-reset-password"),
            {
                "uid": uid,
                "token": token,
                "new_password": "Attacker-overwrite-552!",
            },
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            User.objects.select_for_update().get(pk=user.pk)
            future = pool.submit(submit_legacy)
            _wait_until_lock_wait(pid_queue.get(timeout=5))
            confirm_password_reset(user.email, code, OTP_PASSWORD)
        status_code, body = future.result(timeout=10)

    assert status_code == 400
    assert body == b'{"detail":"Invalid or expired verification code."}'
    user.refresh_from_db()
    assert user.check_password(OTP_PASSWORD)
    assert not user.check_password("Attacker-overwrite-552!")


def test_change_password_waiting_behind_otp_rechecks_current_password(monkeypatch):
    user = make_user("race-change-otp")
    code = issue_otp(user, monkeypatch)
    access = str(RefreshToken.for_user(user).access_token)
    pid_queue = queue.Queue()

    def submit_change():
        return _thread_post(
            pid_queue,
            reverse("auth-change-password"),
            {
                "current_password": "Starting-password-419!",
                "new_password": "Attacker-overwrite-552!",
            },
            access=access,
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            User.objects.select_for_update().get(pk=user.pk)
            future = pool.submit(submit_change)
            _wait_until_lock_wait(pid_queue.get(timeout=5))
            confirm_password_reset(user.email, code, OTP_PASSWORD)
        status_code, body = future.result(timeout=10)

    assert status_code == 400
    assert b"current_password" in body
    user.refresh_from_db()
    assert user.check_password(OTP_PASSWORD)
    assert not user.check_password("Attacker-overwrite-552!")


def _thread_post(pid_queue, url, payload, *, access=None):
    close_old_connections()
    try:
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            pid_queue.put(cursor.fetchone()[0])
        client = APIClient()
        if access:
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = client.post(url, payload, format="json")
        return response.status_code, response.content
    finally:
        close_old_connections()


def _wait_until_lock_wait(pid):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [pid]
            )
            row = cursor.fetchone()
        if row and row[0] == "Lock":
            return
        time.sleep(0.01)
    raise AssertionError("concurrent request never blocked on the user row lock")
