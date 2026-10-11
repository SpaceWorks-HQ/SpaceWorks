"""Reviewed digest preference is a Boolean, never a credential hash."""

WP3_NON_CREDENTIAL = {
    ('notifications.MemberNotificationPreference', 'daily_digest'):
        'Boolean opt-in to daily notification batching, not an authentication digest.',
}
