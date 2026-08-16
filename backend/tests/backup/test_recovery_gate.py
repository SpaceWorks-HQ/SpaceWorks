import pytest
from django.urls import path, reverse
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView
from drf_spectacular.generators import SchemaGenerator

from apps.backup.models import DeploymentRecoveryState
from apps.backup.route_guard import (
    RecoveryRouteConfigurationError,
    validate_recovery_route_allowlists,
)
from apps.backup.route_policy import route_allowed


class ReadView(APIView):
    def get(self, request):
        return Response({})


def test_shipped_recovery_allowlists_resolve_and_middleware_is_first(settings):
    assert validate_recovery_route_allowlists()
    assert settings.MIDDLEWARE[0] == "apps.backup.middleware.DeploymentRecoveryGateMiddleware"


def test_guard_rejects_an_allowed_method_the_view_does_not_handle():
    patterns = [path("api/v1/recovery-probe", ReadView.as_view(), name="probe")]
    policies = {("probe", "POST"), ("probe", "OPTIONS")}
    with pytest.raises(RecoveryRouteConfigurationError, match="POST"):
        validate_recovery_route_allowlists(
            patterns, policy_sets=(("quarantined", policies),)
        )


def test_method_keying_keeps_new_handlers_default_denied():
    assert route_allowed("quarantined", "auth-login", "POST")
    assert not route_allowed("quarantined", "auth-login", "GET")
    assert not route_allowed("quarantined", "auth-login", "PUT")
    assert not route_allowed("quarantined", "telegram-webhook", "POST")


def test_openapi_documents_every_backup_and_recovery_operation():
    paths = SchemaGenerator().get_schema(request=None, public=True)["paths"]
    expected = {
        "/api/v1/admin/platform/backup-settings": {"get", "patch"},
        "/api/v1/admin/platform/backups": {"get", "post"},
        "/api/v1/admin/makerspace/{makerspace_id}/backups": {"get", "post"},
        "/api/v1/admin/backups/{archive_id}/download-url": {"post"},
        "/api/v1/backups/download/{archive_id}/{token}": {"get"},
        "/api/v1/admin/platform/restores": {"get", "post"},
        "/api/v1/admin/platform/restores/{restore_id}": {"get"},
        "/api/v1/admin/platform/restores/{restore_id}/decision": {"post"},
        "/api/v1/recovery": {"get", "post"},
    }
    for path, methods in expected.items():
        assert path in paths
        assert methods <= set(paths[path])


@pytest.mark.django_db
def test_quarantine_gate_is_global_and_runs_before_endpoint_authentication():
    state = DeploymentRecoveryState.load()
    state.mode = DeploymentRecoveryState.Mode.QUARANTINED
    state.save(update_fields=("mode", "updated_at"))
    client = APIClient()

    assert client.get(reverse("health")).status_code == 200
    assert client.post(reverse("auth-login"), {}, format="json").status_code != 503
    assert client.get(reverse("auth-login")).status_code == 503
    assert client.post(reverse("telegram-webhook"), {}, format="json").status_code == 503
    # The recovery view reaches its own authentication layer; it is not rejected by
    # the pre-auth global gate.
    assert client.get(reverse("backup-recovery-state")).status_code == 401


@pytest.mark.django_db
def test_quiescence_allows_only_health_and_the_active_restore_decision_surface():
    state = DeploymentRecoveryState.load()
    state.mode = DeploymentRecoveryState.Mode.QUIESCED
    state.save(update_fields=("mode", "updated_at"))
    client = APIClient()

    assert client.get(reverse("health")).status_code == 200
    assert client.post(reverse("auth-login"), {}, format="json").status_code == 503
