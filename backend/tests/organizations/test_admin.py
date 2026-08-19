import pytest
from django.contrib import admin

from apps.organizations.admin import OrganizationMakerspaceInline
from apps.organizations.models import Organization, OrganizationMakerspace
from config.admin_access import GLOBAL_ADMIN_MODELS, NESTED_MAKERSPACE_LOOKUPS
from config.unfold import UNFOLD


def test_organization_admin_and_link_admin_have_the_required_scope_decisions():
    organization_admin = admin.site._registry[Organization]
    link_admin = admin.site._registry[OrganizationMakerspace]

    assert "organizations.organization" in GLOBAL_ADMIN_MODELS
    assert "organizations.organizationmakerspace" not in GLOBAL_ADMIN_MODELS
    assert "organizations.organizationmakerspace" not in NESTED_MAKERSPACE_LOOKUPS
    assert organization_admin.resolve_hidden_lookup() is None
    assert link_admin.resolve_hidden_lookup() == "makerspace_id"


def test_organization_admin_exposes_makerspace_links_inline():
    organization_admin = admin.site._registry[Organization]

    assert OrganizationMakerspaceInline in organization_admin.inlines


def test_organization_sidebar_link_resolves():
    matching = [
        item
        for group in UNFOLD["SIDEBAR"]["navigation"]
        for item in group["items"]
        if item["route"] == "admin:organizations_organization_changelist"
    ]

    assert len(matching) == 1
    assert str(matching[0]["link"])



@pytest.mark.django_db
def test_hidden_makerspace_links_are_invisible_and_undeletable():
    """The hard-hide invariant must hold through the GLOBAL organization admin.

    Organization resolves as a global model, so it does not inherit the scoped admin's
    filtering; a link to a makerspace with superadmin_access_enabled=False must still be
    hidden from the inline and must block deletion of the organization.
    """
    from django.contrib.admin.sites import AdminSite
    from django.core.exceptions import PermissionDenied

    from apps.makerspaces.models import Makerspace
    from apps.organizations.admin import (
        OrganizationAdmin,
        OrganizationMakerspaceInline,
    )
    from apps.organizations.models import Organization, OrganizationMakerspace

    organization = Organization.objects.create(name="Hidden Link Org", slug="hidden-org")
    hidden = Makerspace.objects.create(name="Hidden Space", slug="hidden-space")
    Makerspace.objects.filter(pk=hidden.pk).update(superadmin_access_enabled=False)
    OrganizationMakerspace.objects.create(
        organization=organization,
        makerspace=hidden,
        relationship=OrganizationMakerspace.Relationship.MANAGER,
    )

    from django.contrib.auth import get_user_model
    from django.test import RequestFactory

    superuser = get_user_model().objects.create_superuser(
        username="hidden-link-super",
        email="hidden-link-super@example.test",
        password="x",
    )
    request = RequestFactory().get("/control/")
    request.user = superuser

    site = AdminSite()
    inline = OrganizationMakerspaceInline(Organization, site)
    assert not inline.get_queryset(request).filter(makerspace=hidden).exists()

    org_admin = OrganizationAdmin(Organization, site)
    assert org_admin.has_delete_permission(request, obj=organization) is False
    with pytest.raises(PermissionDenied):
        org_admin.delete_queryset(
            request, Organization.objects.filter(pk=organization.pk)
        )
