"""Console reach changes retain provenance without reviving source organization grants."""
import pytest

from apps.tenant_migration.audit_reference_guards import validate_audit_meta_references
from apps.tenant_migration.audit_references import AUDIT_META_REFERENCES
from apps.tenant_migration.audit_references_targets import AuditReferenceDisposition
from apps.tenant_migration.reference_guards import ReferenceRegistryError
from apps.tenant_migration.semantic_remap import _remap_audit_dict


@pytest.mark.parametrize("action", [
    "organization.link_created", "organization.link_updated", "organization.link_deleted",
])
def test_link_audit_keeps_source_local_organization_id(action):
    class Map:
        def lookup(self, model, source_pk):
            pytest.fail("Source organization authority must never be remapped.")

    result = _remap_audit_dict(action, {"organization_id": 17, "relationship": "owner"}, Map(), "")
    assert result == {"organization_id": 17, "relationship": "owner"}
    assert AUDIT_META_REFERENCES[(action, "organization_id")].disposition is AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT


def test_link_delete_audit_guard_requires_organization_declaration():
    declarations = dict(AUDIT_META_REFERENCES)
    del declarations[("organization.link_deleted", "organization_id")]
    with pytest.raises(ReferenceRegistryError, match="audit meta ID paths drifted"):
        validate_audit_meta_references(declarations)
