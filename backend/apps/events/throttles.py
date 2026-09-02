import hashlib

from rest_framework.throttling import SimpleRateThrottle

from apps.apiclients.throttling import ClientTierRateThrottle


class CollaborativeRegistrationThrottle(ClientTierRateThrottle):
    """New registrations share the create budget; repair retries get their own.

    The create scope is deliberately the SAME as `PublicEventRegistrationView`'s. Both
    resolve to DRF's `ScopedRateThrottle` cache key (authenticated user pk), so one member
    gets ONE budget across both routes -- which is what closes the bypass, since
    `_collaborative_events()` includes events hosted by the member's own space and the two
    routes therefore reach the same event. `MemberPrincipalRateThrottle` would emit a
    `member:<pk>` ident -- a different key -- and hand out the limit twice.

    But the create budget must never gate a REPAIR. DRF checks throttles in `initial()`,
    before `post()` runs, so a 429 never reaches the `DuplicateRegistration` handler where
    `_stamp_host_waiver` fixes a registration holding no acceptance -- and because the
    bucket is shared, the public route could exhaust it and strand the member at the door.

    Only the statuses that actually take that repair path qualify. A **CANCELLED** row does
    not: `services_registration.register()` REACTIVATES it as a fresh registration instead
    of raising `DuplicateRegistration`, so counting it as a retry would let a member cancel
    and re-register indefinitely on the larger budget -- the create limit bypassed by
    another route.
    """

    def allow_request(self, request, view):
        from apps.events.models import EventRegistration

        user = getattr(request, "user", None)
        repairable = False
        if getattr(user, "is_authenticated", False):
            repairable = (
                EventRegistration.objects.filter(
                    event_id=view.kwargs.get("pk"), member=user,
                )
                .exclude(status=EventRegistration.Status.CANCELLED)
                .exists()
            )
        # ScopedRateThrottle reads the scope off the VIEW at allow_request time, so the
        # selection has to be written there rather than onto this instance.
        view.throttle_scope = (
            "event_registration_retry" if repairable else "event_register"
        )
        return super().allow_request(request, view)


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


class EventCalendarFeedTokenThrottle(SimpleRateThrottle):
    scope = "event_calendar_feed_token"

    def get_cache_key(self, request, view):
        raw_token = view.kwargs.get("raw_token", "")
        if not raw_token:
            return None
        digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}


class EventCalendarFeedIpThrottle(SimpleRateThrottle):
    scope = "event_calendar_feed_ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
