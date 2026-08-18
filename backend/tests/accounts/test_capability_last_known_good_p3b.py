"""Last-known-good protection for capability reads on authentication paths."""

import logging

import pytest
from django.core.cache import cache

from apps.accounts import login_methods, member_identity
from apps.accounts.models import PlatformLoginMethods


def configured_switches(**overrides):
    values = {
        "password_enabled": True,
        "social_enabled": True,
        "phone_enabled": True,
        "self_registration_enabled": True,
    }
    values.update(overrides)
    return PlatformLoginMethods(**values)


def explode(*args, **kwargs):
    raise RuntimeError("capability storage unavailable")


def test_successful_login_methods_read_caches_boolean_values_without_writing(
    monkeypatch,
):
    switches = configured_switches(password_enabled=False)
    monkeypatch.setattr(
        PlatformLoginMethods, "load", classmethod(lambda cls: switches)
    )
    monkeypatch.setattr(
        PlatformLoginMethods,
        "save",
        lambda *args, **kwargs: pytest.fail(
            "the capability read wrote to the database"
        ),
    )

    assert login_methods.password_login_enabled() is False
    assert cache.get(login_methods.LOGIN_METHODS_CACHE_KEY) == {
        "password_enabled": False,
        "social_enabled": True,
        "phone_enabled": True,
        "self_registration_enabled": True,
    }
    assert switches._state.adding is True


def test_failed_login_methods_read_keeps_cached_disabled_method(monkeypatch, caplog):
    cache.set(
        login_methods.LOGIN_METHODS_CACHE_KEY,
        {
            "password_enabled": False,
            "social_enabled": True,
            "phone_enabled": True,
            "self_registration_enabled": True,
        },
        timeout=None,
    )
    monkeypatch.setattr(PlatformLoginMethods, "load", classmethod(explode))

    with caplog.at_level(logging.ERROR, logger=login_methods.__name__):
        assert login_methods.password_login_enabled() is False

    assert "login_methods_read_failed" in caplog.text


def test_failed_login_methods_read_without_cache_uses_permissive_default(
    monkeypatch, caplog
):
    cache.delete(login_methods.LOGIN_METHODS_CACHE_KEY)
    monkeypatch.setattr(PlatformLoginMethods, "load", classmethod(explode))

    with caplog.at_level(logging.ERROR, logger=login_methods.__name__):
        switches = login_methods._switches()

    assert all(getattr(switches, field) for field in login_methods._SWITCH_FIELDS)
    assert "login_methods_read_failed" in caplog.text


def test_successful_member_accounts_read_populates_cache(monkeypatch):
    import apps.makerspaces.deployment_modules as deployment_modules

    monkeypatch.setattr(deployment_modules, "member_accounts_enabled", lambda: False)

    assert member_identity.member_accounts_enabled() is False
    assert cache.get(member_identity.MEMBER_ACCOUNTS_CACHE_KEY) is False


def test_failed_member_accounts_read_keeps_cached_disabled_value(monkeypatch, caplog):
    import apps.makerspaces.deployment_modules as deployment_modules

    cache.set(member_identity.MEMBER_ACCOUNTS_CACHE_KEY, False, timeout=None)
    monkeypatch.setattr(deployment_modules, "member_accounts_enabled", explode)

    with caplog.at_level(logging.ERROR, logger=member_identity.__name__):
        assert member_identity.member_accounts_enabled() is False

    assert "member_accounts_read_failed" in caplog.text


def test_failed_member_accounts_read_without_cache_fails_open(monkeypatch, caplog):
    import apps.makerspaces.deployment_modules as deployment_modules

    cache.delete(member_identity.MEMBER_ACCOUNTS_CACHE_KEY)
    monkeypatch.setattr(deployment_modules, "member_accounts_enabled", explode)

    with caplog.at_level(logging.ERROR, logger=member_identity.__name__):
        assert member_identity.member_accounts_enabled() is True

    assert "member_accounts_read_failed" in caplog.text
