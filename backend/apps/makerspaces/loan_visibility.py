"""Frontend loan surfaces suppressed by the per-space master switch."""

LOAN_MODULES = frozenset({
    "public_inventory", "request_workflow", "guest_handover", "evidence_uploads",
    "qr_management", "scanner", "bulk_import", "containers", "stock_transfers",
    "stocktake", "qr_print_batches", "asset_units",
})
LOAN_FEATURES = frozenset({
    "inventory.self_checkout", "inventory.kiosk",
})
# Loan policies and money remain available for retained loans. A visibility switch
# must not prevent a returned loan from recording a late fee or settling its debt.
