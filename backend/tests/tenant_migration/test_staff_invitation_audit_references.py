"""Invitation audit IDs must bind to the correct target models after import."""

import pytest

from apps.tenant_migration.audit_reference_guards import validate_audit_meta_references
from apps.tenant_migration.audit_references import AUDIT_META_REFERENCES
from apps.tenant_migration.reference_guards import ReferenceRegistryError
from apps.tenant_migration.semantic_remap import _remap_audit_dict


EDGES = (
    ("staff.invitation_created", "role_id", "makerspaces.MakerspaceRole"),
    ("staff.invitation_accepted", "role_id", "makerspaces.MakerspaceRole"),
    ("staff.invitation_accepted", "membership_id", "makerspaces.MakerspaceMembership"),
)


@pytest.mark.parametrize("action, field, target_label", EDGES)
def test_invitation_audit_meta_remaps_each_id_to_its_declared_model(action, field, target_label):
    class Map:
        def lookup(self, model, source_pk):
            assert model._meta.label == target_label
            assert source_pk == 17
            return 901

    assert _remap_audit_dict(action, {field: 17, "detail": "unchanged"}, Map(), "") == {
        field: 901, "detail": "unchanged",
    }


@pytest.mark.parametrize("action, field, target_label", EDGES)
def test_invitation_audit_meta_guard_refuses_a_missing_declaration(action, field, target_label):
    declarations = dict(AUDIT_META_REFERENCES)
    del declarations[(action, field)]
    with pytest.raises(ReferenceRegistryError, match="audit meta ID paths drifted"):
        validate_audit_meta_references(declarations)
