"""Independent abuse budgets for account-less hardware-request proposals."""

from rest_framework.throttling import SimpleRateThrottle

from apps.accounts.audit_events import fingerprint


class _AnonymousIpThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return None if not ident else self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }


class AnonymousRequestIpBurstThrottle(_AnonymousIpThrottle):
    scope = "anonymous_request_ip_burst"


class AnonymousRequestIpHourThrottle(_AnonymousIpThrottle):
    scope = "anonymous_request_ip_hour"


class AnonymousRequestEmailThrottle(SimpleRateThrottle):
    scope = "anonymous_request_email"

    def get_cache_key(self, request, view):
        email = str(getattr(request, "anonymous_contact_email", "") or "").strip().lower()
        if not email:
            return None
        # Cache keys are operational data at rest. The normalized email is never
        # embedded directly; this follows the password-reset/phone throttle pattern.
        return self.cache_format % {
            "scope": self.scope,
            "ident": fingerprint(email),
        }
