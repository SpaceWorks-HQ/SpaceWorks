from rest_framework.throttling import ScopedRateThrottle


class ArchiveRecipientVerificationThrottle(ScopedRateThrottle):
    """Share one verification-attempt budget across a recipient's operators."""

    def get_cache_key(self, request, view):
        if not self.scope:
            return None
        ident = f"{view.kwargs['makerspace_id']}:{view.kwargs['pk']}"
        return self.cache_format % {"scope": self.scope, "ident": ident}
