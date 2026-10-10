"""Production overlays are tested as layers, not mistaken for standalone manifests."""

import re
from pathlib import Path

import pytest
import yaml

from apps.backup.settings_policy import ENV_SURFACE
from tests.test_env_surface_drift import (
    BACKEND_SERVICES, FRONTEND_KEYS, INFRASTRUCTURE_KEYS, ON_BOX_EXEMPT,
    ON_BOX, _env_calls, _consumer_on_box_fallbacks,
)

ROOT = Path(__file__).resolve().parents[2]


class ComposeLoader(yaml.SafeLoader):
    pass


ComposeLoader.add_constructor("!reset", lambda loader, node: loader.construct_sequence(node))


@pytest.mark.parametrize("overlay", ["saas", "tls", "single"])
def test_effective_overlay_environment_keeps_the_complete_production_posture(overlay):
    base = yaml.load((ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"), Loader=ComposeLoader)
    layer = yaml.load((ROOT / f"docker/compose.{overlay}.yml").read_text(encoding="utf-8"), Loader=ComposeLoader)
    known = set(ENV_SURFACE) | FRONTEND_KEYS | INFRASTRUCTURE_KEYS
    required = {
        name for name, default in _env_calls()
        if default and ON_BOX.search(default) and name not in ON_BOX_EXEMPT
    } | set(_consumer_on_box_fallbacks()) | {"TRUSTED_PROXY_COUNT", "TRUST_X_FORWARDED_PROTO"}
    for service in BACKEND_SERVICES:
        if service not in base["services"]:
            continue
        environment = {
            **base["services"][service].get("environment", {}),
            **layer["services"].get(service, {}).get("environment", {}),
        }
        assert required <= environment.keys(), (overlay, service, required - environment.keys())
        assert set(environment) <= known, (overlay, service, set(environment) - known)
    if overlay == "saas":
        expected = layer["services"]["backend"]["environment"]["PLATFORM_DOMAIN_SUFFIX"]
        for service in ("migrate", "worker", "beat"):
            assert layer["services"][service]["environment"]["PLATFORM_DOMAIN_SUFFIX"] == expected


@pytest.mark.parametrize("example", [".env.example", ".env.production.example", "backend/.env.example"])
def test_env_examples_expose_observability_and_reference_the_complete_surface(example):
    source = (ROOT / example).read_text(encoding="utf-8")
    for name in ("METRICS_TOKEN", "SENTRY_DSN", "SENTRY_TRACES_SAMPLE_RATE", "SENTRY_ENVIRONMENT"):
        assert re.search(rf"^\s*(?:#\s*)?{name}=", source, re.M), (example, name)
    assert "docs/environment-reference.md" in source
