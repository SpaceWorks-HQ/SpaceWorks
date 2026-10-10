"""Managed hosting cells the SaaS suite left open (cloud lane).

* an ARCHIVED tenant's verified domain must lose TLS issuance and host admission at once,
  because VERIFIED is the trust gate only for non-archived spaces;
* a verified custom domain is admitted by the host middleware itself, not only listed;
* provisioning on a self-hosted box is refused, not half-applied.
"""

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import RequestFactory, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DrfValidationError
from rest_framework.test import APIClient

from apps.makerspaces import hosting, middleware
from apps.makerspaces.models import Makerspace
from apps.makerspaces.provisioning import provision_subdomain
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db

MANAGED = {"PLATFORM_DOMAIN_SUFFIX": ".space-works.tech", "INFRA_HOSTS": {"testserver"}}


def _verified(slug, domain):
    space = make_space(slug)
    space.frontend_domain = domain
    space.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    space.save()
    hosting.invalidate()
    return space


def _tls(domain):
    return APIClient().get("/api/v1/internal/tls-check", {"domain": domain}, HTTP_HOST="testserver")


@override_settings(**MANAGED)
def test_archiving_a_tenant_withdraws_tls_issuance_for_its_domain():
    space = _verified("tls-archived", "tools.archived.example")
    assert _tls("tools.archived.example").status_code == 200

    Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now())
    hosting.invalidate()

    assert _tls("tools.archived.example").status_code == 403


@override_settings(**MANAGED)
def test_the_host_middleware_admits_a_verified_custom_domain_and_drops_an_archived_one():
    space = _verified("host-admit", "tools.admit.example")
    seen = []
    gate = middleware.TenantHostValidationMiddleware(lambda request: seen.append(request) or "ok")

    assert gate(RequestFactory().get("/", HTTP_HOST="tools.admit.example")) == "ok"

    Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now())
    hosting.invalidate()
    refused = gate(RequestFactory().get("/", HTTP_HOST="tools.admit.example"))

    assert getattr(refused, "status_code", None) == 400
    assert len(seen) == 1


@override_settings(**MANAGED)
def test_a_subdomain_request_is_audited_and_refused_to_non_managers():
    from django.urls import reverse

    from apps.audit.models import AuditLog
    from apps.makerspaces.models import MakerspaceMembership, SubdomainRequest
    from tests.return_helpers import authenticated_client, make_member

    space = make_space("subdomain-audit")
    url = reverse("admin-makerspace-subdomain-request", kwargs={"makerspace_id": space.id})
    manager = make_member("subdomain-audit-manager", space)
    member = make_member(
        "subdomain-audit-inventory", space, membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER
    )

    refused = authenticated_client(member).post(
        url, {"requested_label": "member-lab"}, format="json", HTTP_HOST="testserver"
    )
    anonymous = APIClient().post(
        url, {"requested_label": "anon-lab"}, format="json", HTTP_HOST="testserver"
    )
    created = authenticated_client(manager).post(
        url, {"requested_label": "audit-lab"}, format="json", HTTP_HOST="testserver"
    )

    assert refused.status_code in {403, 404}  # the view hides the space from non-managers
    assert anonymous.status_code == 401
    assert created.status_code == 201
    row = SubdomainRequest.objects.get(makerspace=space)
    event = AuditLog.objects.get(action="makerspace.subdomain_requested")
    assert event.actor == manager
    assert event.target_id == str(row.pk) or event.makerspace_id == space.pk


@override_settings(PLATFORM_DOMAIN_SUFFIX="")
def test_provisioning_a_subdomain_on_a_self_hosted_box_is_refused():
    space = make_space("provision-self-host")

    with pytest.raises((DjangoValidationError, DrfValidationError), match="not enabled"):
        provision_subdomain(space, "kochi", actor=None)

    space.refresh_from_db()
    assert space.frontend_domain in ("", None)
