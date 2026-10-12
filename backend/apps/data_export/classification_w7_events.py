"""Literal WP1 event additions. No new User FKs; attribution uses AuditLog.actor."""
EVENT_EXPORTED_FIELDS = {
    "events.EventInvite": "id makerspace event code_digest email_digest max_uses uses expires_at revoked_at created_at",
    "events.EventTicketType": "id makerspace event series name amount audience capacity sales_start_at sales_end_at is_active created_at",
    "events.EventPromoCode": "id makerspace event code_digest percent_off amount_off max_uses uses expires_at revoked_at created_at",
    "events.EventCategory": "id makerspace name slug",
}
EVENT_ADDED_FIELDS = {
    "events.EventSeries": "registration_audience",
    "events.Event": "registration_audience category tags",
    "events.EventRegistration": "registration_audience ticket_type invite promo_code quoted_amount discount_amount",
}
EVENT_OMITTED_FIELDS = {
    ("events.EventInvite", "code_digest"): "Source invitation credential; reissue on target.",
    ("events.EventInvite", "email_digest"): "Deployment-local keyed contact digest.",
    ("events.EventPromoCode", "code_digest"): "Source discount credential; reissue on target.",
}


def extend_event_export_fields(fields):
    fields.update(EVENT_EXPORTED_FIELDS)
    for label, names in EVENT_ADDED_FIELDS.items():
        fields[label] += " " + names
