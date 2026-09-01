"""Proxy-aware DRF and django-axes client-IP resolution.

Production must explicitly declare TRUSTED_PROXY_COUNT. Development defaults to zero,
which ignores caller-supplied X-Forwarded-For, while positive counts select the
proxy-appended address from the right of that chain.
"""
import os
import subprocess
import sys
from pathlib import Path

from axes.helpers import get_client_ip_address
from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import BaseThrottle


def _ident(**meta):
    request = APIRequestFactory().get("/", **meta)
    # BaseThrottle.get_ident reads request.META and api_settings.NUM_PROXIES. (Use the
    # base class, not SimpleRateThrottle, which requires a configured scope at init.)
    return BaseThrottle().get_ident(request)


def test_production_settings_refuse_an_unset_proxy_count():
    backend = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update(
        SECRET_KEY="settings-import-test",
        DEBUG="False",
        DATABASE_URL="sqlite:///:memory:",
    )
    environment.pop("TRUSTED_PROXY_COUNT", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import environ; "
                "environ.Env.read_env = lambda *args, **kwargs: None; "
                "import config.settings"
            ),
        ],
        cwd=backend,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "TRUSTED_PROXY_COUNT must be explicitly set" in result.stderr


def test_debug_default_uses_remote_addr(settings):
    assert api_settings.NUM_PROXIES == 0
    assert settings.AXES_IPWARE_PROXY_COUNT == 0
    assert settings.AXES_CLIENT_IP_CALLABLE == "config.client_ip.get_throttle_client_ip"
    assert _ident(
        HTTP_X_FORWARDED_FOR="1.2.3.4",
        REMOTE_ADDR="10.0.0.9",
    ) == "10.0.0.9"


def test_num_proxies_one_takes_real_client_from_xff(settings):
    # One trusted proxy: DRF counts from the right, so the real client is the LAST XFF
    # entry (the one our proxy appended). A client-spoofed prefix ("1.2.3.4") is ignored,
    # and the proxy's own REMOTE_ADDR ("172.16.0.1") is not used as the throttle key.
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    settings.AXES_IPWARE_PROXY_COUNT = 1
    api_settings.reload()
    try:
        request = APIRequestFactory().get(
            "/",
            HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.7",
            REMOTE_ADDR="172.16.0.1",
        )
        assert BaseThrottle().get_ident(request) == "203.0.113.7"
        assert get_client_ip_address(request) == "203.0.113.7"
    finally:
        api_settings.reload()


def test_num_proxies_zero_ignores_xff(settings):
    # Zero trusted proxies: XFF is untrusted, REMOTE_ADDR wins even when XFF is spoofed.
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 0}
    settings.AXES_IPWARE_PROXY_COUNT = 0
    api_settings.reload()
    try:
        request = APIRequestFactory().get(
            "/",
            HTTP_X_FORWARDED_FOR="1.2.3.4",
            REMOTE_ADDR="172.16.0.1",
        )
        assert BaseThrottle().get_ident(request) == "172.16.0.1"
        assert get_client_ip_address(request) == "172.16.0.1"
    finally:
        api_settings.reload()
