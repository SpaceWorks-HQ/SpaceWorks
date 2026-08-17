"""Row-existence dispositions for movable and cross-tenant references."""

from dataclasses import dataclass
from enum import StrEnum


class MissingReferenceDisposition(StrEnum):
    NULL_WITH_PROVENANCE = "null_with_provenance"
    DROP_WITH_PROVENANCE = "drop_with_provenance"
    INERT_WITH_PROVENANCE = "inert_with_provenance"


@dataclass(frozen=True)
class RowReferenceRule:
    target_model_label: str
    disposition: MissingReferenceDisposition
    reason: str
    anchor_field: str | None = None


# Every concrete relation to a row whose tenant ownership can change is declared here.
# A present target remaps normally; the disposition applies only when that target row
# is outside the archive's tenant closure.
MOVABLE_ROW_REFERENCES = {
    # A completed request/asset link is immutable lending history. The link cannot
    # legally survive without its non-null asset, so preserve it as provenance
    # anchored to the imported request item and drop only the unusable live edge.
    ("hardware_requests.HardwareRequestItemAsset", "asset"): RowReferenceRule(
        "inventory.InventoryAsset",
        MissingReferenceDisposition.DROP_WITH_PROVENANCE,
        "A moved asset leaves an anchored historical handover snapshot.",
        anchor_field="request_item",
    ),
    # These stocktake/ledger rows remain useful history with an explicitly null asset;
    # the typed snapshot distinguishes that state from a row that never named an asset.
    ("operations.StocktakeLine", "asset"): RowReferenceRule(
        "inventory.InventoryAsset",
        MissingReferenceDisposition.NULL_WITH_PROVENANCE,
        "Retain the count while making the displaced asset edge inert.",
        anchor_field="stocktake",
    ),
    ("operations.InventoryAdjustment", "asset"): RowReferenceRule(
        "inventory.InventoryAsset",
        MissingReferenceDisposition.NULL_WITH_PROVENANCE,
        "Retain quantity history without binding a foreign asset id.",
    ),
    ("operations.StocktakeLedgerEntry", "asset"): RowReferenceRule(
        "inventory.InventoryAsset",
        MissingReferenceDisposition.NULL_WITH_PROVENANCE,
        "Retain the ledger entry and externalize its displaced asset.",
        anchor_field="stocktake",
    ),
    # A transfer line requires exactly one product/asset in application semantics.
    # Nulling its only subject would create a misleading live transfer line.
    ("operations.StockTransferLine", "asset"): RowReferenceRule(
        "inventory.InventoryAsset",
        MissingReferenceDisposition.DROP_WITH_PROVENANCE,
        "A displaced serialized transfer line is preserved as typed provenance.",
        anchor_field="transfer",
    ),
    # Warranty has a database constraint requiring exactly one live host. A moved
    # asset therefore externalizes the warranty edge instead of fabricating a host.
    ("warranty.Warranty", "asset"): RowReferenceRule(
        "inventory.InventoryAsset",
        MissingReferenceDisposition.DROP_WITH_PROVENANCE,
        "A warranty for a moved asset cannot remain a constrained live row.",
    ),
    # Immutable scans and print items require non-null QR rows. Both become typed
    # history rather than binding the source numeric id to an unrelated target QR.
    ("boxes.QrScanEvent", "qr_code"): RowReferenceRule(
        "boxes.QrCode",
        MissingReferenceDisposition.DROP_WITH_PROVENANCE,
        "An immutable scan of a moved QR becomes anchored scan provenance.",
        anchor_field="request",
    ),
    ("operations.QrPrintBatchItem", "qr_code"): RowReferenceRule(
        "boxes.QrCode",
        MissingReferenceDisposition.DROP_WITH_PROVENANCE,
        "Printed-label history is externalized when its QR moved away.",
        anchor_field="batch",
    ),
    # The loan itself remains valuable and its FK is nullable. The external snapshot
    # makes this distinguishable from a loan that was originally recorded without QR.
    ("hardware_requests.PublicToolLoan", "qr_code"): RowReferenceRule(
        "boxes.QrCode",
        MissingReferenceDisposition.NULL_WITH_PROVENANCE,
        "Retain the loan with an explicitly externalized primary QR.",
    ),
}


MOVABLE_LIST_REFERENCES = {
    ("hardware_requests.PublicToolLoan", "asset_ids"): RowReferenceRule(
        "inventory.InventoryAsset",
        MissingReferenceDisposition.INERT_WITH_PROVENANCE,
        "Remap archived assets and externalize only absent asset ids.",
    ),
    ("hardware_requests.PublicToolLoan", "qr_ids"): RowReferenceRule(
        "boxes.QrCode",
        MissingReferenceDisposition.INERT_WITH_PROVENANCE,
        "Remap archived QRs and externalize only absent QR ids.",
    ),
}


MOVABLE_DISCRIMINATOR_REFERENCES = {
    ("boxes.QrCode", "target_type", "target_id"): {
        "asset": RowReferenceRule(
            "inventory.InventoryAsset",
            MissingReferenceDisposition.DROP_WITH_PROVENANCE,
            "A QR cannot remain live when its asset target is outside the archive.",
        ),
    },
    ("hardware_requests.PublicToolLoan", "target_type", "target_id"): {
        "asset": RowReferenceRule(
            "inventory.InventoryAsset",
            MissingReferenceDisposition.INERT_WITH_PROVENANCE,
            "A displaced loan target becomes external_asset:0 plus typed provenance.",
        ),
    },
    ("operations.QrPrintBatchItem", "target_type", "target_id"): {
        "asset": RowReferenceRule(
            "inventory.InventoryAsset",
            MissingReferenceDisposition.DROP_WITH_PROVENANCE,
            "A displaced printed asset label is provenance, not a live numeric target.",
            anchor_field="batch",
        ),
    },
}


# These row-context edges cannot be inferred from a nullable/non-null FK alone.
CROSS_TENANT_DEPENDENT_REFERENCES = {
    ("operations.StockTransfer", "inbound_transfer"): (
        MissingReferenceDisposition.DROP_WITH_PROVENANCE
    ),
    ("operations.StockTransferLine", "inbound_transfer"): (
        MissingReferenceDisposition.DROP_WITH_PROVENANCE
    ),
    ("operations.InventoryAdjustment", "transfer"): (
        MissingReferenceDisposition.NULL_WITH_PROVENANCE
    ),
    # Warranty documents cannot outlive a dropped constrained Warranty row. Their
    # metadata receives its own typed sidecar rather than failing at PK remap time.
    ("warranty.WarrantyDocument", "external_warranty"): (
        MissingReferenceDisposition.DROP_WITH_PROVENANCE
    ),
}
