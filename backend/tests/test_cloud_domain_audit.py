"""A domain's trust boundary changes must retain before/after evidence."""

import pytest
from django.test import override_settings
from django.contrib import admin
from django.contrib.messages import get_messages

from apps.audit.models import AuditLog
from apps.makerspaces.admin_subdomains import SubdomainRequestAdmin
from apps.makerspaces.models import SubdomainRequest
from tests.return_helpers import authenticated_client, make_space
from tests.test_subdomain_approval import make_admin_request, make_pending_request, make_superadmin

pytestmark = pytest.mark.django_db


@override_settings(PLATFORM_DOMAIN_SUFFIX="")
def test_setting_and_clearing_domain_records_before_and_after():
    space = make_space("domain-audit")
    root = make_superadmin("domain-audit-root")
    client = authenticated_client(root)
    url = f"/api/v1/admin/makerspaces/{space.pk}"
    for before, after in [(None, "tools.example.org"), ("tools.example.org", None)]:
        response = client.patch(url, {"frontend_domain": after or ""}, format="json")
        assert response.status_code == 200
        entry = AuditLog.objects.filter(action="makerspace.frontend_domain_changed").latest("id")
        assert (entry.meta["before"] or None, entry.meta["after"] or None) == (before, after)
        assert entry.actor == root and entry.makerspace_id == space.pk
    count = AuditLog.objects.filter(action="makerspace.frontend_domain_changed").count()
    assert client.patch(url, {"frontend_domain": ""}, format="json").status_code == 200
    assert AuditLog.objects.filter(action="makerspace.frontend_domain_changed").count() == count


@override_settings(PLATFORM_DOMAIN_SUFFIX="")
def test_self_host_approval_reports_disabled_provisioning_not_existing_subdomain():
    space, _, row = make_pending_request("self-host-approval", "lab")
    space.frontend_domain = "tools.example.org"
    space.save()
    request = make_admin_request(make_superadmin("self-host-approval-root"))
    SubdomainRequestAdmin(SubdomainRequest, admin.site).approve_and_provision(
        request, SubdomainRequest.objects.filter(pk=row.pk),
    )
    messages = " ".join(str(message) for message in get_messages(request))
    assert "not enabled" in messages
    assert "already has a platform subdomain" not in messages
    row.refresh_from_db()
    assert row.status == SubdomainRequest.Status.PENDING
    assert not AuditLog.objects.filter(action="makerspace.subdomain_request_approved").exists()
