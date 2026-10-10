from collections.abc import Mapping

from rest_framework.throttling import SimpleRateThrottle

from apps.accounts.audit_events import fingerprint


class MFAChallengeThrottle(SimpleRateThrottle):
    scope = "mfa_challenge"

    def get_cache_key(self, request, view):
        value = str(request.data.get("challenge") or "")[:200] if isinstance(request.data, Mapping) else ""
        return self.cache_format % {"scope": self.scope, "ident": fingerprint(value)}


class MFAUserThrottle(SimpleRateThrottle):
    """Keep the budget across new challenges and changes of IP address."""
    scope = "mfa_user"

    def get_cache_key(self, request, view):
        from apps.accounts.mfa_challenges import digest
        from apps.accounts.models_mfa import MFAChallenge
        raw = str(request.data.get("challenge") or "")[:200] if isinstance(request.data, Mapping) else ""
        user_id = MFAChallenge.objects.filter(token_digest=digest(raw)).values_list("user_id", flat=True).first()
        if user_id is None:
            return None
        return self.cache_format % {"scope": self.scope, "ident": fingerprint(user_id)}
