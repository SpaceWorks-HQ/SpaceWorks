"""`ENABLE_HTTPS=true` must not redirect the deployment's own plain-HTTP probes (cloud lane).

The TLS, SaaS and cloud stacks turn `ENABLE_HTTPS` on, which turns `SECURE_SSL_REDIRECT`
on. Every caller that reaches the backend port directly speaks plain HTTP -- the compose
healthchecks, Caddy's on-demand TLS ask and a Prometheus scrape -- and a 301 to `https://`
on a port with no TLS is a failure: the healthcheck never passes and no custom-domain
certificate is ever issued. Browser traffic is unaffected because it arrives through the
TLS proxy already marked secure.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

BACKEND = Path(__file__).resolve().parent.parent

PROBES = (
    "/api/v1/health/",
    "/api/v1/health/readiness/",
    "/api/v1/internal/tls-check?domain=tools.example.org",
    "/api/v1/metrics/",
)


@pytest.mark.parametrize("path", PROBES)
def test_internal_probes_are_answered_over_plain_http_when_the_redirect_is_on(path):
    from django.conf import settings

    with override_settings(
        SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=settings.SECURE_REDIRECT_EXEMPT
    ):
        response = APIClient().get(path)

    assert response.status_code != 301, f"{path} was redirected to {response.get('Location')}"


def test_ordinary_api_traffic_is_still_redirected_to_https():
    from django.conf import settings

    with override_settings(
        SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=settings.SECURE_REDIRECT_EXEMPT
    ):
        response = APIClient().get("/api/v1/public/makerspaces/")

    assert response.status_code == 301
    assert response["Location"].startswith("https://")


def test_a_request_marked_secure_by_the_proxy_is_never_redirected():
    from django.conf import settings

    with override_settings(
        SECURE_SSL_REDIRECT=True,
        SECURE_REDIRECT_EXEMPT=settings.SECURE_REDIRECT_EXEMPT,
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    ):
        response = APIClient().get(
            "/api/v1/public/makerspaces/", HTTP_X_FORWARDED_PROTO="https"
        )

    assert response.status_code != 301


def test_enable_https_turns_the_whole_tls_posture_on_and_keeps_the_exemption():
    """Settings are module-level, so the ENABLE_HTTPS branch is read in a fresh process."""
    env = {**os.environ, "ENABLE_HTTPS": "true", "DJANGO_SETTINGS_MODULE": "config.settings"}
    env.pop("SECURE_SSL_REDIRECT", None)
    env.pop("SECURE_HSTS_SECONDS", None)
    script = (
        "import json, django; django.setup(); from django.conf import settings as s; "
        "print(json.dumps({k: getattr(s, k) for k in ("
        "'SECURE_SSL_REDIRECT', 'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE', "
        "'SECURE_HSTS_SECONDS', 'SECURE_HSTS_INCLUDE_SUBDOMAINS', 'SECURE_REDIRECT_EXEMPT')}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=BACKEND, env=env,
        capture_output=True, text=True, timeout=120, check=True,
    )
    values = json.loads(result.stdout.strip().splitlines()[-1])

    assert values["SECURE_SSL_REDIRECT"] is True
    assert values["SESSION_COOKIE_SECURE"] is True
    assert values["CSRF_COOKIE_SECURE"] is True
    assert values["SECURE_HSTS_SECONDS"] == 31536000
    assert values["SECURE_HSTS_INCLUDE_SUBDOMAINS"] is True
    assert r"^api/v1/health/" in values["SECURE_REDIRECT_EXEMPT"]
    assert r"^api/v1/internal/" in values["SECURE_REDIRECT_EXEMPT"]
