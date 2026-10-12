"""Independent literal WP1 model/field review; no source access codes survive import."""
EVENT_PROJECTED_MODELS = frozenset({"events.EventInvite", "events.EventTicketType", "events.EventPromoCode", "events.EventCategory"})
EVENT_FIELD_NAMES = {
    "events.EventInvite": frozenset("id makerspace event code_digest email_digest max_uses uses expires_at revoked_at created_at".split()),
    "events.EventTicketType": frozenset("id makerspace event series name amount audience capacity sales_start_at sales_end_at is_active created_at".split()),
    "events.EventPromoCode": frozenset("id makerspace event code_digest percent_off amount_off max_uses uses expires_at revoked_at created_at".split()),
    "events.EventCategory": frozenset("id makerspace name slug".split()),
}
EVENT_ADDED_FIELDS = {
    "events.EventSeries": frozenset("registration_audience".split()),
    "events.Event": frozenset("registration_audience category tags".split()),
    "events.EventRegistration": frozenset("registration_audience ticket_type invite promo_code quoted_amount discount_amount".split()),
}


def extend_event_field_snapshot(fields):
    fields.update(EVENT_FIELD_NAMES)
    for label, names in EVENT_ADDED_FIELDS.items():
        fields[label] |= names
