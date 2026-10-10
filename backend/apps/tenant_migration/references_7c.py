"""All label snapshots are source-local history, not target lookups."""
LABEL_SNAPSHOT_FIELDS = frozenset(
    ("devices.LabelPrintCommand", name)
    for name in ("batch_id_snapshot", "batch_title_snapshot", "item_count_snapshot")
)
