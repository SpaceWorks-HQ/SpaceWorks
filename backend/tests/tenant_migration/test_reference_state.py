import json

from apps.tenant_migration.reference_state import ReferenceState
from apps.tenant_migration.verification import _verify_loan_reference_list


class OrdinaryProvenanceReferences(ReferenceState):
    def __init__(self):
        pass

    def get(self, model_label, source_object_id, field_name):
        assert (model_label, source_object_id, field_name) == (
            "hardware_requests.PublicToolLoan",
            41,
            "asset_ids",
        )
        return {"kind": "ordinary_provenance", "detail": "bare provenance detail"}


class RemappedAssetIds:
    def lookup(self, model, source_id):
        assert model._meta.label == "inventory.InventoryAsset"
        return {17: 701}[int(source_id)]


def test_loan_list_verification_ignores_ordinary_provenance_record():
    source = {"id": 41, "asset_ids": json.dumps([17])}
    actual = {"asset_ids": [701]}

    _verify_loan_reference_list(
        source,
        actual,
        RemappedAssetIds(),
        OrdinaryProvenanceReferences(),
        "asset_ids",
        "inventory.InventoryAsset",
    )
