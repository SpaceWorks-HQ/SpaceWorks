"""Independent literal snapshots, unioned into the model and field catalogs."""
LABEL_PROJECTED_MODELS = frozenset({"devices.LabelPrintCommand", "devices.LabelPrintResult"})
LABEL_FIELD_NAMES = {
    "devices.LabelPrintCommand": frozenset((
        "id command makerspace device batch request_id batch_id_snapshot batch_title_snapshot "
        "item_count_snapshot result result_code result_message completed_at requested_by created_at"
    ).split()),
    "devices.LabelPrintResult": frozenset((
        "id makerspace label_command operation_id outcome result_code response_result "
        "response_command_status response_completed_at created_at"
    ).split()),
}
