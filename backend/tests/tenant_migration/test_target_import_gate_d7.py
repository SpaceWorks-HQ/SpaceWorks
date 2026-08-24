from apps.backup.middleware import DeploymentRecoveryGateMiddleware
from apps.backup.models import DeploymentRecoveryState
from apps.backup.route_policy import route_allowed


def test_target_import_is_health_only_and_unknown_mode_is_default_deny():
    assert route_allowed("target_import", "health", "GET")
    assert route_allowed("target_import", "readiness", "GET")
    assert not route_allowed("target_import", "auth-login", "POST")
    assert not route_allowed("unavailable", "health", "GET")


def test_missing_recovery_singleton_is_not_treated_as_normal(monkeypatch):
    class Query:
        def only(self, *_fields):
            return self

        def filter(self, **_lookup):
            return self

        def first(self):
            return None

    monkeypatch.setattr(DeploymentRecoveryState, "objects", Query())
    assert DeploymentRecoveryGateMiddleware._load_mode() == "unavailable"
