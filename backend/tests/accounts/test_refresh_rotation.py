from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from apps.accounts.models import User
from apps.accounts.serializers import SpaceWorksTokenRefreshSerializer
from apps.accounts.tokens import SpaceWorksRefreshToken


pytestmark = pytest.mark.django_db(transaction=True)

REFRESH = "/api/v1/auth/refresh"
ORIGIN = "http://localhost:5000"


def test_concurrent_refresh_rotation_mints_one_usable_descendant(
    settings, monkeypatch
):
    settings.CORS_ALLOWED_ORIGINS = [ORIGIN]
    user = User.objects.create_user(
        username="concurrent-refresh",
        password="refresh-password-451!",
        access_status=User.AccessStatus.ACTIVE,
    )
    original = str(SpaceWorksRefreshToken.for_user(user))
    decoded = Barrier(2)

    class SynchronizedRefreshToken(SpaceWorksRefreshToken):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            decoded.wait(timeout=10)

    monkeypatch.setattr(
        SpaceWorksTokenRefreshSerializer,
        "token_class",
        SynchronizedRefreshToken,
    )

    def rotate():
        close_old_connections()
        client = APIClient()
        client.cookies["refresh_token"] = original
        try:
            return client.post(
                REFRESH,
                HTTP_X_REFRESH_CSRF="1",
                HTTP_ORIGIN=ORIGIN,
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _index: rotate(), range(2)))

    assert sorted(response.status_code for response in responses) == [200, 401]
    loser = next(response for response in responses if response.status_code == 401)
    assert loser.data["code"] == "token_not_valid"

    winner = next(response for response in responses if response.status_code == 200)
    descendant = winner.cookies["refresh_token"].value
    assert OutstandingToken.objects.filter(user=user).count() == 2
    monkeypatch.setattr(
        SpaceWorksTokenRefreshSerializer,
        "token_class",
        SpaceWorksRefreshToken,
    )
    client = APIClient()
    client.cookies["refresh_token"] = descendant
    assert client.post(
        REFRESH,
        HTTP_X_REFRESH_CSRF="1",
        HTTP_ORIGIN=ORIGIN,
    ).status_code == 200
