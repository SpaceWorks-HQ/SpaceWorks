"""WP1 features: opt-in additions under the existing events module."""


def event_features(feature_type):
    return (
        feature_type("events.invites", "events", "Event invitations"),
        feature_type("events.account_registration", "events", "Account event registration"),
        feature_type("events.ticket_types", "events", "Event ticket types"),
        feature_type("events.promo_codes", "events", "Event promo codes", requires_features=("events.ticket_types",)),
    )
