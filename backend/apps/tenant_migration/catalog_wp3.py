"""Literal WP3 schema, unioned before the catalog drift guards run."""

WP3_PROJECTED_LABELS = frozenset({'notifications.MemberBroadcast'})
WP3_FIELD_NAMES = {
    'notifications.MemberBroadcast': frozenset('id makerspace created_by title body created_at'.split()),
    'integrations.NotificationTimingPolicy': frozenset('id makerspace quiet_start quiet_end channels digest_at bounce_secret'.split()),
    'bookings.BookingCalendarFeed': frozenset('id makerspace user token_digest token_hint created_at rotated_at revoked_at'.split()),
}
WP3_EXTRA_FIELDS = {
    'notifications.MemberNotificationPreference': frozenset({'daily_digest'}),
    'bookings.Booking': frozenset({'calendar_sequence', 'calendar_updated_at'}),
}


def wp3_authority(authority, disposition):
    reason = 'Source calendar tokens and mail policy never become target disclosure authority.'
    return {
        **{('bookings.BookingCalendarFeed', name): authority(disposition.DROP, reason)
           for name in ('user', 'token_digest', 'token_hint', 'revoked_at')},
        **{('integrations.NotificationTimingPolicy', name): authority(disposition.DROP, reason)
           for name in ('quiet_start', 'quiet_end', 'channels', 'digest_at', 'bounce_secret')},
        ('notifications.MemberNotificationPreference', 'daily_digest'): authority(disposition.DROP, reason),
        ('bookings.Booking', 'calendar_sequence'): authority(
            disposition.RESET, 'New target calendar subscriptions start a fresh update sequence.',
        ),
    }
