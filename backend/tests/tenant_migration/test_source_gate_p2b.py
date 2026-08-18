import json

import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.tenant_migration.middleware import SourceMigrationGateMiddleware
from tests.tenant_migration.source_gate_helpers import (
    close_gate,
    make_actor,
    make_space,
)


pytestmark = pytest.mark.django_db(transaction=True)


def test_conflicting_hint_uses_authoritative_object_tenant_gate():
    actor = make_actor("p2b-conflict")
    hinted_space = make_space("p2b-hinted")
    object_space = make_space("p2b-object")
    target = MakerspaceMembership.objects.create(
        makerspace=object_space,
        user=actor,
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    close_gate(object_space, actor)
    middleware = SourceMigrationGateMiddleware(
        lambda _request: HttpResponse(status=204)
    )
    url = reverse("admin-membership-capabilities", args=[target.pk])

    response = middleware(
        RequestFactory().patch(
            f"{url}?makerspace_id={hinted_space.pk}",
            data="{}",
            content_type="application/json",
        )
    )

    assert response.status_code == 423
    assert json.loads(response.content)["code"] == "tenant_migration_quiesced"


def test_unscoped_login_is_not_refused_while_a_tenant_is_quiesced():
    actor = make_actor("p2b-login")
    frozen = make_space("p2b-login-frozen")
    close_gate(frozen, actor)
    middleware = SourceMigrationGateMiddleware(
        lambda _request: HttpResponse(status=204)
    )

    response = middleware(RequestFactory().post(reverse("auth-login")))

    assert response.status_code == 204


def test_unresolvable_object_route_keeps_view_outcome_instead_of_423():
    actor = make_actor("p2b-unresolved")
    frozen = make_space("p2b-unresolved-frozen")
    frozen.frontend_domain = "p2b-unresolved.example.test"
    frozen.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    frozen.save(update_fields=["frontend_domain", "frontend_domain_status"])
    close_gate(frozen, actor)
    middleware = SourceMigrationGateMiddleware(
        lambda _request: HttpResponse(status=404)
    )
    url = reverse("admin-membership-capabilities", args=[2_147_483_647])

    response = middleware(
        RequestFactory().patch(
            f"{url}?makerspace_id=bogus",
            data="{}",
            content_type="application/json",
            HTTP_ORIGIN="https://p2b-unresolved.example.test",
        )
    )

    assert response.status_code == 404
