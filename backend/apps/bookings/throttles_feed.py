"""Use the existing calendar rate budgets with separate hashed booking token keys."""

import hashlib
from rest_framework.throttling import SimpleRateThrottle


class BookingFeedTokenThrottle(SimpleRateThrottle):
    scope = 'event_calendar_feed_token'

    def get_cache_key(self, request, view):
        raw = view.kwargs.get('raw_token', '')
        return self.cache_format % {'scope': 'booking_calendar_feed_token',
                                   'ident': hashlib.sha256(raw.encode()).hexdigest()}


class BookingFeedIpThrottle(SimpleRateThrottle):
    scope = 'event_calendar_feed_ip'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': 'booking_calendar_feed_ip', 'ident': self.get_ident(request)}
