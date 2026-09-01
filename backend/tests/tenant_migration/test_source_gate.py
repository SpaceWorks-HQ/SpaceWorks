import json
import uuid
from datetime import timedelta

import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from apps.makerspaces.models import Makerspace
from apps.tenant_migration.gate_errors import (
    SourceMigrationGateClosed,
    SourceMigrationOwnershipError,
)
from apps.tenant_migration.gate_runtime import source_archive_write
from apps.tenant_migration.middleware import SourceMigrationGateMiddleware
from apps.tenant_migration.models import SourceMigrationGate
from apps.tenant_migration.source_gate import (
    GateLease,
    claim,
    heartbeat,
    quiesced_snapshot,
)
from tests.tenant_migration.source_gate_helpers import (
    close_gate as _closed,
    make_actor as _actor,
    make_space as _space,
)


pytestmark = pytest.mark.django_db(transaction=True)

def test_scoped_refusal_never_becomes_a_deployment_wide_423():
    actor = _actor()
    frozen = _space("frozen")
    frozen.frontend_domain = "frozen.example.test"
    frozen.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    frozen.save(update_fields=["frontend_domain", "frontend_domain_status"])
    unrelated = _space("unrelated")
    _closed(frozen, actor)
    middleware = SourceMigrationGateMiddleware(lambda _request: HttpResponse(status=204))
    requests = RequestFactory()

    frozen_response = middleware(
        requests.post(f"/api/v1/public/{frozen.slug}/membership-requests")
    )
    unrelated_response = middleware(
        requests.post(f"/api/v1/public/{unrelated.slug}/membership-requests")
    )
    login_response = middleware(
        requests.post("/api/v1/auth/login", HTTP_ORIGIN="https://frozen.example.test")
    )
    refresh_response = middleware(
        requests.post("/api/v1/auth/refresh", HTTP_ORIGIN="https://frozen.example.test")
    )

    assert frozen_response.status_code == 423
    assert json.loads(frozen_response.content)["code"] == "tenant_migration_quiesced"
    assert unrelated_response.status_code == 204
    assert login_response.status_code == 204
    assert refresh_response.status_code == 204


def test_late_service_guard_refusal_is_rendered_as_typed_423():
    middleware = SourceMigrationGateMiddleware(lambda _request: HttpResponse(status=204))
    response = middleware.process_exception(
        RequestFactory().post("/api/v1/unscoped"),
        SourceMigrationGateClosed("Tenant writes are frozen."),
    )

    assert response.status_code == 423
    assert json.loads(response.content) == {
        "detail": "Tenant writes are frozen.",
        "code": "tenant_migration_quiesced",
    }


def test_login_and_refresh_remain_available_while_one_tenant_is_closed(settings):
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:5000"]
    actor = _actor("global-auth")
    space = _space("global-auth")
    _closed(space, actor)
    client = APIClient()

    login = client.post(
        "/api/v1/auth/login",
        {"username": actor.username, "password": "gate-test-password"},
        format="json",
    )
    refresh = client.post(
        "/api/v1/auth/refresh",
        HTTP_X_REFRESH_CSRF="1",
        HTTP_ORIGIN="http://localhost:5000",
    )

    assert login.status_code == 200
    assert refresh.status_code == 200


def test_unknown_public_tenant_does_not_replace_the_view_outcome():
    middleware = SourceMigrationGateMiddleware(
        lambda _request: HttpResponse(status=403)
    )

    response = middleware(
        RequestFactory().post(
            "/api/v1/public/unknown-source-gate-space/membership-requests"
        )
    )

    assert response.status_code == 403


def test_stale_or_expired_owner_has_no_authority(settings):
    settings.TENANT_MIGRATION_PRESIGN_DRAIN_SECONDS = 0
    space = _space("fencing")
    actor = _actor("fencing")
    lease = claim(space, actor)

    stale_token = GateLease(
        space.pk, lease.owner_id, lease.fencing_token - 1,
        lease.state, lease.lease_expires_at,
    )
    with pytest.raises(SourceMigrationOwnershipError):
        heartbeat(stale_token)
    with pytest.raises(SourceMigrationGateClosed):
        with source_archive_write(
            space.pk, stale_token.owner_id, stale_token.fencing_token
        ):
            pass
    with pytest.raises(SourceMigrationOwnershipError, match="fencing token"):
        with quiesced_snapshot(
            space,
            actor,
            owner_id=stale_token.owner_id,
            fencing_token=stale_token.fencing_token,
            sleep=lambda _seconds: None,
        ):
            pass

    stale_owner = GateLease(
        space.pk, uuid.uuid4(), lease.fencing_token,
        lease.state, lease.lease_expires_at,
    )
    with pytest.raises(SourceMigrationOwnershipError):
        heartbeat(stale_owner)

    SourceMigrationGate.objects.filter(makerspace=space).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(SourceMigrationOwnershipError):
        heartbeat(lease)
    with pytest.raises(SourceMigrationOwnershipError):
        with quiesced_snapshot(
            space,
            actor,
            owner_id=lease.owner_id,
            fencing_token=lease.fencing_token,
            sleep=lambda _seconds: None,
        ):
            pass
    with pytest.raises(SourceMigrationGateClosed):
        with source_archive_write(space.pk, lease.owner_id, lease.fencing_token):
            pass


def test_same_owner_claim_resumes_without_bumping_fence(settings):
    settings.TENANT_MIGRATION_PRESIGN_DRAIN_SECONDS = 0
    space = _space("resume")
    actor = _actor("resume")
    owner = uuid.uuid4()
    first = claim(space, actor, owner_id=owner)
    second = claim(
        space, actor, owner_id=owner, fencing_token=first.fencing_token
    )

    assert second.owner_id == first.owner_id
    assert second.fencing_token == first.fencing_token
    assert SourceMigrationGate.objects.get(makerspace=space).fencing_token == 1
