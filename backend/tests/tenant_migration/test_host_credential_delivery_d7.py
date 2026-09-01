import pytest

from apps.tenant_migration.host_credential_delivery import CredentialDeliveryStore
from apps.tenant_migration.tenant_restore_types import TenantRestoreRefused


def test_unacknowledged_secret_is_durably_reused_then_tombstoned(tmp_path):
    store = CredentialDeliveryStore(tmp_path, require_root_owned=False)
    provenance = "a" * 64
    first = store.get_or_prepare(
        provenance=provenance,
        kind="api_client",
        target="source-ref",
        secret_factory=lambda: "first-secret",
    )
    second = store.get_or_prepare(
        provenance=provenance,
        kind="api_client",
        target="source-ref",
        secret_factory=lambda: "must-not-be-used",
    )

    assert first == second
    assert (tmp_path / f"{provenance}.secret.json").stat().st_mode & 0o777 == 0o600
    store.acknowledge(provenance, host_principal="root@host")
    assert not (tmp_path / f"{provenance}.secret.json").exists()
    assert (tmp_path / f"{provenance}.ack.json").exists()
    with pytest.raises(TenantRestoreRefused, match="already acknowledged"):
        store.read_unacknowledged(provenance)
