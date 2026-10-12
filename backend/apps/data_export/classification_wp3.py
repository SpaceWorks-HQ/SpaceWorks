"""WP3 history travels; inbound secrets and live calendar/delivery controls do not."""

WP3_EXPORTED_FIELDS = {
    'notifications.MemberBroadcast': 'id makerspace created_by title body created_at',
}
WP3_OMITTED_MODELS = {
    'integrations.NotificationTimingPolicy': 'Source-local delivery timing and encrypted inbound signing authority.',
    'bookings.BookingCalendarFeed': 'Source-bound calendar disclosure capability; users issue new target tokens.',
}
