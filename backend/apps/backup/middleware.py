from django.db import OperationalError, ProgrammingError
from django.http import JsonResponse
from django.urls import Resolver404, resolve

from apps.backup.models import DeploymentRecoveryState
from apps.backup.route_policy import route_allowed


class DeploymentRecoveryGateMiddleware:
    """Global, default-deny request gate for quiescence and disaster recovery.

    This reads the mode from the database on EVERY request, deliberately and without a cache.
    A cache was written and removed: it bought an amortised query at the cost of a staleness
    window in which a deployment that had just been quarantined would keep serving traffic,
    which is the one failure this gate exists to prevent. It also made the per-request query
    count depend on cache warmth, which broke three query-count tests that capture a count and
    then assert equality -- the first request paid for the lookup and later ones did not.

    The cost is one primary-key lookup on a single-row table, served from shared buffers. If
    that ever needs optimising, the answer is a mechanism with no staleness window (a
    connection-level or LISTEN/NOTIFY-driven invalidation), not a TTL.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            mode = self._load_mode()
        except (OperationalError, ProgrammingError):
            return self._refused("unavailable")
        if mode == DeploymentRecoveryState.Mode.NORMAL:
            return self.get_response(request)
        try:
            view_name = resolve(request.path_info).view_name or ""
        except Resolver404:
            return self._refused(mode)
        if not route_allowed(mode, view_name, request.method):
            return self._refused(mode)
        return self.get_response(request)

    @staticmethod
    def _load_mode():
        state = DeploymentRecoveryState.objects.only("mode").filter(pk=1).first()
        return state.mode if state else DeploymentRecoveryState.Mode.NORMAL

    @staticmethod
    def _refused(mode):
        detail = (
            "This deployment is in recovery quarantine. Only recovery routes are available."
            if mode == DeploymentRecoveryState.Mode.QUARANTINED
            else "This deployment is temporarily quiesced for restore."
        )
        return JsonResponse(
            {"detail": detail, "code": f"deployment_{mode}"}, status=503
        )

