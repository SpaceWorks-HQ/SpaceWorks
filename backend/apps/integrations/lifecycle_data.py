"""The structured notification contract admits identifiers, never template context."""

DOMAIN_ID_FIELDS = frozenset({
    "request_id", "payment_id", "booking_id", "space_id", "event_id", "series_id",
    "registration_id", "machine_id", "schedule_id", "maintenance_log_id",
    "membership_request_id", "membership_id", "api_key_request_id",
    "machine_service_request_id",
    "refund_id", "to_buy_item_id", "pool_id", "certification_grant_id",
    "certification_type_id",
    "product_id",
})


def lifecycle_data(data):
    """Copy only documented numeric IDs; refuse bool/string/contact/credential values."""
    return {
        key: value for key, value in (data or {}).items()
        if key in DOMAIN_ID_FIELDS and type(value) is int and value > 0
    }


def structured_event(log):
    """Additive versioned object; the existing webhook envelope stays compatible."""
    data = log.payload or {}
    return {
        "version": 1,
        "event": f"{log.feature}.{log.event}",
        "ids": lifecycle_data(data),
        "makerspace": {"id": log.makerspace_id},
        "occurred_at": data.get("occurred_at") or (
            log.created_at.isoformat() if log.created_at else None
        ),
    }
