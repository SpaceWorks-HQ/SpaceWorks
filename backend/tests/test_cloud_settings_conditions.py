"""Import-time cloud settings, exercised in isolated interpreters without a database."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured
from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory

from config.client_ip import get_throttle_client_ip

BACKEND = Path(__file__).resolve().parents[1]


def import_settings(script, **overrides):
    environment = {
        **os.environ, "SECRET_KEY": "cloud-settings-test", "DEBUG": "True",
        "DATABASE_URL": "sqlite:///:memory:", "TRUSTED_PROXY_COUNT": "0",
        "SENTRY_DSN": "", "CACHE_URL": "", "CELERY_BROKER_URL": "",
        **overrides,
    }
    return subprocess.run(
        [sys.executable, "-c", "import environ; environ.Env.read_env = lambda *a, **k: None; " + script],
        cwd=BACKEND, env=environment, capture_output=True, text=True, timeout=30,
    )


def test_negative_proxy_count_refuses_startup():
    result = import_settings("import config.settings", TRUSTED_PROXY_COUNT="-1")
    assert result.returncode != 0
    assert "TRUSTED_PROXY_COUNT cannot be negative" in result.stderr


def test_axes_and_drf_must_agree_on_the_proxy_chain(settings):
    settings.AXES_IPWARE_PROXY_COUNT = 1
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 0}
    api_settings.reload()
    try:
        with pytest.raises(ImproperlyConfigured, match="must match"):
            get_throttle_client_ip(APIRequestFactory().get("/"))
    finally:
        api_settings.reload()


@pytest.mark.parametrize("url,backend", [
    ("", "django.core.cache.backends.db.DatabaseCache"),
    ("redis://cache:6379/1", "django.core.cache.backends.redis.RedisCache"),
])
def test_redis_and_database_cache_selection(url, backend):
    result = import_settings(
        "import config.settings as s; print(s.CACHES['default']['BACKEND'])", CACHE_URL=url,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == backend


def test_forwarded_proto_setting_changes_djangos_secure_request_detection():
    result = import_settings(
        "import config.settings as s; print(s.SECURE_PROXY_SSL_HEADER)",
        TRUST_X_FORWARDED_PROTO="true",
    )
    assert result.returncode == 0, result.stderr
    assert "('HTTP_X_FORWARDED_PROTO', 'https')" in result.stdout


def test_sentry_unset_never_imports_the_sdk():
    result = import_settings(
        "import sys; import config.settings; print('sentry_sdk' in sys.modules)"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "False"


def test_sentry_configured_has_both_integrations_and_no_default_pii():
    script = """
import json, sys, types
sdk = types.ModuleType('sentry_sdk')
sdk.init = lambda **values: print(json.dumps({**values, 'integrations': [type(v).__name__ for v in values['integrations']]}))
sys.modules['sentry_sdk'] = sdk
for name in ('Celery', 'Django'):
    module = types.ModuleType('sentry_sdk.integrations.' + name.lower())
    setattr(module, name + 'Integration', type(name + 'Integration', (), {}))
    sys.modules[module.__name__] = module
import config.settings
"""
    result = import_settings(script, SENTRY_DSN="https://key@sentry.example/1", SENTRY_TRACES_SAMPLE_RATE="0.0")
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout.strip().splitlines()[-1])
    assert values["integrations"] == ["DjangoIntegration", "CeleryIntegration"]
    assert values["send_default_pii"] is False
    assert values["traces_sample_rate"] == 0.0
