"""Exact label route tenant resolution; object kwargs remain pk."""
LABEL_MODEL_LOOKUPS = {
    "admin-label-command-list": ("operations.QrPrintBatch", "makerspace_id"),
    "device-label-command-content": ("devices.LabelPrintCommand", "makerspace_id"),
    "device-label-command-result": ("devices.LabelPrintCommand", "makerspace_id"),
}
