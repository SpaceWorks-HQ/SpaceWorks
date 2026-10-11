"""WP3 capability rows; imported only after FeatureDefinition is defined."""

def wp3_features(definition):
    return (
        definition('notifications.quiet_hours', 'notifications', 'Quiet hours'),
        definition('notifications.digests', 'notifications', 'Daily notification digests'),
        definition('membership.broadcasts', 'membership', 'Member broadcasts', requires_modules=('notifications',)),
        definition('bookings.recurring', 'bookings', 'Recurring bookings'),
    )
