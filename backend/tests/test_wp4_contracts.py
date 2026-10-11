"""New domain rows must remain portable without transferring source authority."""

import pytest
from django.utils import timezone

from apps.data_export.guards import validate_all
from apps.data_export.models import MODELS
from apps.data_export.types import OmittedModel
from apps.tenant_migration.authority_guards import validate_authority_registry
from apps.tenant_migration.projection_guards import validate_projection_registry
from apps.tenant_migration.target_projection import TARGET_FIELD_PROJECTION, ROW_POLICIES, RowDisposition
from apps.tenant_migration.tenant_dump_catalog import validate_field_coverage, FIELD_POLICIES, catalog_models
from apps.tenant_migration.audit_references import AUDIT_TARGET_DISPOSITIONS, AuditReferenceDisposition
from apps.makerspaces.module_purge import purge_module
from apps.accounts.models import User
from apps.operations.models import StocktakePolicy, StocktakeSchedule
from apps.maintenance.models_feed import MaintenanceCalendarFeed
from tests.maintenance.helpers import make_machine_setup
from tests.module_helpers import disable_module

pytestmark = pytest.mark.django_db(transaction=True)


def test_wp4_export_projection_authority_and_schema_coverage():
    validate_all()
    validate_authority_registry()
    validate_projection_registry()
    # Check actual model fields against reviewed declarations. Computing an expected
    # hash from the very graph under test would silently bless arbitrary schema drift.
    # The integration catalog tests check the independently pinned merged digest.
    validate_field_coverage(catalog_models(), FIELD_POLICIES)
    for label in ("inventory.InventoryWatch", "maintenance.MaintenanceCalendarFeed"):
        assert isinstance(MODELS[label], OmittedModel)
        assert ROW_POLICIES[label].disposition is RowDisposition.DROP
    assert TARGET_FIELD_PROJECTION[("machines.Machine", "public_fields")].resolved_value("machines.Machine", "public_fields") == []
    assert TARGET_FIELD_PROJECTION[("operations.StocktakeSchedule", "is_active")].value is False
    for label in ("machines.machinematerial", "operations.stocktakeschedule"):
        assert AUDIT_TARGET_DISPOSITIONS[label].disposition is AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT


def test_module_purges_delete_stocktake_preferences_and_feed_credentials_only_in_space():
    space, actor, _, _ = make_machine_setup("wp4-purge")
    other, other_actor, _, _ = make_machine_setup("wp4-purge-other")
    admin = User.objects.create_superuser(username="wp4-purge-admin", email="admin@example.test", password="test")
    for tenant, user in ((space, actor), (other, other_actor)):
        StocktakePolicy.objects.create(makerspace=tenant)
        StocktakeSchedule.objects.create(makerspace=tenant, name="Monthly", interval_days=30, next_due=timezone.localdate())
        MaintenanceCalendarFeed.objects.create(makerspace=tenant, user=user, token_digest=bytes([tenant.pk % 256])*32, token_hint="12345678")
    disable_module(space, "stocktake")
    disable_module(space, "maintenance")
    purge_module(space, "stocktake", admin)
    purge_module(space, "maintenance", admin)
    for model in (StocktakePolicy, StocktakeSchedule, MaintenanceCalendarFeed):
        assert not model.objects.filter(makerspace=space).exists()
        assert model.objects.filter(makerspace=other).exists()
