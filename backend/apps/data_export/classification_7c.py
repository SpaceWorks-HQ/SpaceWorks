"""Literal label history: no bytes, credential, free-form message or object field."""
LABEL_EXPORTED_MODEL_FIELDS = {
    "devices.LabelPrintCommand": (
        "id command makerspace device batch request_id batch_id_snapshot batch_title_snapshot "
        "item_count_snapshot result result_code result_message completed_at requested_by created_at"
    ),
    "devices.LabelPrintResult": (
        "id makerspace label_command operation_id outcome result_code response_result "
        "response_command_status response_completed_at created_at"
    ),
}
