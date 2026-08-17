import pytest
from django.contrib import admin
from django.urls import Resolver404, resolve

from apps.separability.registry import runtime_active
from apps.tenant_migration.models import (
    DisclosureClosureApproval,
    TenantMigrationExportJob,
)

pytestmark = pytest.mark.django_db


def test_tenant_migration_is_registered_inactive():
    assert runtime_active("tenant_migration") is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/platform/tenant-migrations/deployment-identity",
        "/api/v1/admin/platform/tenant-migrations/imports",
        "/api/v1/admin/platform/tenant-migrations/imports/00000000-0000-0000-0000-000000000001",
        "/api/v1/admin/platform/tenant-migrations/imports/00000000-0000-0000-0000-000000000001/identity-decisions",
        "/api/v1/admin/platform/tenant-migrations/imports/00000000-0000-0000-0000-000000000001/run",
        "/api/v1/admin/platform/tenant-migrations/imports/00000000-0000-0000-0000-000000000001/verification",
        "/api/v1/admin/platform/tenant-migrations/imports/00000000-0000-0000-0000-000000000001/pairings/00000000-0000-0000-0000-000000000002/activate",
        "/api/v1/admin/platform/tenant-migrations/imports/00000000-0000-0000-0000-000000000001/pairings/00000000-0000-0000-0000-000000000002/abort",
        "/api/v1/admin/platform/tenant-migrations/pairings",
        "/api/v1/admin/makerspace/1/tenant-migration/disclosure-closure",
        "/api/v1/admin/makerspace/1/tenant-migration/disclosure-approvals",
        "/api/v1/admin/makerspace/1/tenant-migration/disclosure-approvals/00000000-0000-0000-0000-000000000001/revoke",
        "/api/v1/admin/makerspace/1/tenant-migration/exports",
        "/api/v1/admin/makerspace/1/tenant-migration/exports/00000000-0000-0000-0000-000000000001",
        "/api/v1/admin/makerspace/1/tenant-migration/exports/00000000-0000-0000-0000-000000000001/download-url",
        "/api/v1/admin/makerspace/1/tenant-migration/exports/00000000-0000-0000-0000-000000000001/quiesce",
        "/api/v1/admin/makerspace/1/tenant-migration/pairings/00000000-0000-0000-0000-000000000001/archive-source",
        "/api/v1/admin/makerspace/1/tenant-migration/pairings/00000000-0000-0000-0000-000000000001/recover",
    ],
)
def test_no_tenant_migration_route_resolves(path):
    with pytest.raises(Resolver404):
        resolve(path)


def test_neighbouring_data_export_route_still_resolves():
    assert resolve("/api/v1/admin/makerspace/1/data-exports").url_name == (
        "data-export-list-create"
    )


def test_runtime_admin_models_are_not_registered():
    assert DisclosureClosureApproval not in admin.site._registry
    assert TenantMigrationExportJob not in admin.site._registry
