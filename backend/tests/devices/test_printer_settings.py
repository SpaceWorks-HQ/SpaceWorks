"""Exact new env defaults and backup compatibility policy, independent of DB."""
from pathlib import Path

from apps.backup.settings_policy import POLICIES, Policy


def test_command_defaults_are_declared_in_every_env_example_and_excluded_from_restore_compatibility():
    root = Path(__file__).resolve().parents[3]
    expected = {"DEVICE_COMMAND_LEASE_SECONDS": 60, "DEVICE_COMMAND_MAX_ATTEMPTS": 10}
    for name, default in expected.items():
        policy = POLICIES[name]
        assert policy.policy is Policy.EXCLUDED and not policy.secret_bearing and not policy.blocks_restore
        for filename in (".env.example", ".env.production.example", "backend/.env.example"):
            assert f"{name}={default}" in (root / filename).read_text(encoding="utf-8-sig")
    settings_source = (root / "backend/config/settings.py").read_text(encoding="utf-8-sig")
    for name, default in expected.items():
        assert f'{name} = env.int("{name}", default={default})' in settings_source


def test_nonpositive_command_tuning_is_rejected_by_system_checks():
    from django.test import override_settings
    from apps.devices.checks import check_device_protocol_settings
    for settings_override in ({"DEVICE_COMMAND_LEASE_SECONDS": 0}, {"DEVICE_COMMAND_MAX_ATTEMPTS": 0}):
        with override_settings(**settings_override):
            assert "devices.E004" in {error.id for error in check_device_protocol_settings()}
