from datetime import datetime, timezone


SOURCE_REVIEWED = "request"
SOURCE_SELF_CHECKOUT = "self_checkout"
SOURCE_DIRECT = "direct_handout"
SOURCE_QUERY_VALUES = {
    "reviewed": SOURCE_REVIEWED,
    "request": SOURCE_REVIEWED,
    "self_checkout": SOURCE_SELF_CHECKOUT,
    "direct": SOURCE_DIRECT,
    "direct_handout": SOURCE_DIRECT,
}
SORT_FIELDS = {
    "item_name": "ledger_item_name",
    "holder": "holder_sort_id",
    "quantity": "quantity",
    "since": "since_sort",
    "due": "due_sort",
    "source": "ledger_source",
    "makerspace_id": "ledger_makerspace_id",
}
LEDGER_COLUMNS = [
    "ledger_source",
    "ledger_item_name",
    "ledger_container",
    "holder_sort_id",
    "quantity",
    "ledger_target_label",
    "since",
    "due",
    "since_sort",
    "due_sort",
    "overdue",
    "ledger_makerspace_id",
    "reference_id",
    "ledger_status",
    "row_group",
    "ledger_request_id",
    "ledger_item_id",
    "ledger_product_id",
    "loan_id",
]
_FLOOR = datetime.min.replace(tzinfo=timezone.utc)
_CEILING = datetime.max.replace(tzinfo=timezone.utc)
