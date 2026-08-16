from django.db import OperationalError, ProgrammingError
from django.http import JsonResponse
from django.urls import Resolver404, resolve

from apps.backup import recovery_cache
from apps.backup.models import DeploymentRecoveryState
from apps.backup.route_policy import route_allowed


class DeploymentRecoveryGateMiddleware:
    """Global, default-deny request gate for quiescence and disaster recovery."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            mode = recovery_cache.cached_mode(self._load_mode)
        except (OperationalError, ProgrammingError):
            # Fail closed, and do not cache the failure: an unreadable state must refuse
            # every request rather than be remembered as NORMAL for the TTL.
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

