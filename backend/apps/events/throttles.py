from rest_framework.throttling import SimpleRateThrottle


class EventCheckInResolveThrottle(SimpleRateThrottle):
    """Bound repeated resolve attempts by the authenticated staff principal.

    UUID4 entropy makes token enumeration infeasible. Authorization, event scoping,
    and a uniform 404 prevent a stolen token from becoming a cross-tenant oracle; this
    throttle bounds abuse rather than serving as the primary control.
    """

    scope = "event_checkin_resolve"

    def get_cache_key(self, request, view):
        if request.method != "POST":
            return None
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": user.pk}
