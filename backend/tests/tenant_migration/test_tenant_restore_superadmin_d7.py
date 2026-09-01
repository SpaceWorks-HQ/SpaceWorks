import inspect
import uuid

import pytest

from apps.accounts.models import User
from apps.tenant_migration.host_credential_delivery import CredentialDeliveryStore
from apps.tenant_migration import (
    tenant_restore_activation,
    tenant_restore_orchestrator,
    tenant_restore_target_state,
)
from apps.tenant_migration.tenant_restore_superadmin import create_target_superadmin
from apps.tenant_migration.tenant_restore_types import TenantRestoreRefused


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("username", "is_active"),
    [("imported-full", True), ("__tenant_stub__artifact_ref", False)],
)
def test_target_superadmin_email_refuses_an_imported_full_user_or_stub(
    tmp_path, username, is_active
):
    User.objects.create_user(
        username=username,
        email="operator@example.test",
        password=None,
        is_active=is_active,
    )
    delivery = CredentialDeliveryStore(tmp_path, require_root_owned=False)

    with pytest.raises(TenantRestoreRefused, match="imported user or stub"):
        create_target_superadmin(
            email="operator@example.test",
            run_id=uuid.uuid4(),
            artifact_sha256="a" * 64,
            delivery_store=delivery,
        )


def test_ordered_restore_path_never_calls_password_invalidating_quarantine():
    for module in (
        tenant_restore_activation,
        tenant_restore_orchestrator,
        tenant_restore_target_state,
    ):
        assert "enter_quarantine" not in inspect.getsource(module)
