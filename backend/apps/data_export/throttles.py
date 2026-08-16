from rest_framework.throttling import SimpleRateThrottle


class DataExportCreateThrottle(SimpleRateThrottle):
    """Expensive snapshot jobs are capped per authenticated staff principal."""

    scope = "data_export_create"

    def get_cache_key(self, request, view):
        if request.method != "POST":
            return None
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": user.pk}
