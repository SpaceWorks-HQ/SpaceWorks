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

