import hashlib

from rest_framework.throttling import SimpleRateThrottle


class StationTokenThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        token = str(view.kwargs.get("public_token", ""))
        if not token:
            return None
        ident = hashlib.sha256(token.encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": ident}


class StationIpThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class StationActorThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": user.pk}
