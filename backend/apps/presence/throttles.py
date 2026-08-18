from datetime import timedelta

from apps.apiclients.throttling import MemberPrincipalRateThrottle
from apps.makerspaces.lookup import get_public_makerspace
from apps.presence import services


class PresenceStartThrottle(MemberPrincipalRateThrottle):
    """Charge starts that create a row while leaving exact replays idempotent."""

    def allow_request(self, request, view):
        if self._is_idempotent_replay(request, view):
            return True
        return super().allow_request(request, view)

    @staticmethod
    def _is_idempotent_replay(request, view):
        try:
            duration = int(request.data.get("duration_minutes"))
        except (AttributeError, TypeError, ValueError):
            return False
        makerspace_slug = view.kwargs.get("makerspace_slug")
        if not makerspace_slug:
            return False
        makerspace = get_public_makerspace(makerspace_slug)
        session = services.current_session(request.user, makerspace)
        return bool(
            session
            and session.expires_at - session.started_at
            == timedelta(minutes=duration)
        )
