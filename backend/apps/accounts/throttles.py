from rest_framework.throttling import SimpleRateThrottle


class PasswordResetEmailThrottle(SimpleRateThrottle):
    scope = "password_reset_email"

    def get_cache_key(self, request, view):
        from apps.accounts.audit_events import fingerprint

        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": fingerprint(email),
        }


class PasswordResetConfirmEmailThrottle(PasswordResetEmailThrottle):
    """Per-address guessing budget, separate from the resend allowance."""

    scope = "password_reset_confirm_email"


class MemberVerificationEmailThrottle(SimpleRateThrottle):
    scope = "member_verification_email"

    def get_cache_key(self, request, view):
        email = request.data.get("email") or getattr(request.user, "email", "")
        email = email.strip().lower()
        if not email:
            return None
        return self.cache_format % {"scope": self.scope, "ident": email}


MemberSignUpEmailThrottle = MemberVerificationEmailThrottle


class PhoneOtpNumberThrottle(SimpleRateThrottle):
    """Per-number cap, so one handset cannot be texted repeatedly from many IPs.

    Keyed on a fingerprint of the submitted number, never the number itself: throttle
    keys land in the cache and a raw phone number there is PII at rest.
    """

    scope = "phone_otp_number"

    def get_cache_key(self, request, view):
        from apps.accounts.audit_events import fingerprint
        from apps.accounts.phone_numbers import normalize_or_none

        phone = normalize_or_none(request.data.get("phone"))
        return None if not phone else self.cache_format % {
            "scope": self.scope, "ident": fingerprint(phone)
        }


class PhoneConfirmNumberThrottle(PhoneOtpNumberThrottle):
    """Per-number cap on code GUESSES, budgeted separately from code REQUESTS.

    Sharing one bucket with PhoneOtpNumberThrottle looked tidier and was wrong: a
    member who mistypes a code three times would spend the same allowance used to send
    it and be locked out for an hour with a valid code in hand. Guessing and requesting
    are different actions with different abuse profiles, so they get different budgets.
    The per-challenge attempt counter is still the tighter of the two limits.
    """

    scope = "phone_confirm_number"


class PhoneOtpRequestThrottle(SimpleRateThrottle):
    """Per-IP cap on code requests -- the number-enumeration sweep defence."""

    scope = "phone_otp_request"

    def get_cache_key(self, request, view):
        return self.get_ident(request) and self.cache_format % {
            "scope": self.scope, "ident": self.get_ident(request)
        }


class PhoneLoginConfirmThrottle(SimpleRateThrottle):
    """Per-IP cap on code guesses.

    The per-challenge attempt counter caps guesses against ONE challenge; this caps an
    attacker who keeps requesting fresh challenges to reset that counter.
    """

    scope = "phone_login_confirm"

    def get_cache_key(self, request, view):
        return self.get_ident(request) and self.cache_format % {
            "scope": self.scope, "ident": self.get_ident(request)
        }


class DeviceLoginThrottle(SimpleRateThrottle):
    scope = "device_login"

    def get_cache_key(self, request, view):
        return self.get_ident(request) and self.cache_format % {
            "scope": self.scope, "ident": self.get_ident(request)
        }


class DeviceLoginUserThrottle(SimpleRateThrottle):
    scope = "device_login_user"

    def get_cache_key(self, request, view):
        from apps.accounts.audit_events import fingerprint

        username = str(request.data.get("username") or "").strip().lower()
        return None if not username else self.cache_format % {
            "scope": self.scope, "ident": fingerprint(username)
        }
