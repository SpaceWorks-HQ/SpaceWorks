"""WP3 schedules/tokens are DROP models; imported message content stays inert history."""

def wp3_projections(field_type):
    return {
        ('bookings.Booking', 'calendar_sequence'): field_type(
            0, reason='New target calendar subscriptions start a fresh update sequence.',
        ),
    }
