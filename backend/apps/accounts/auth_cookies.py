from urllib.parse import urlsplit

from django.conf import settings
from rest_framework.exceptions import PermissionDenied

from apps.makerspaces.cors import member_origin_is_registered, staff_origin_is_registered


def _refresh_max_age():
    return int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())


def set_refresh_cookies(response, refresh_token, request=None):
    """Set the long-lived httpOnly refresh cookie.

    Explicit max_age (review fix #7) - without it the cookie would be a session cookie
    and die on browser close, despite the 7-day token lifetime."""
    max_age = _refresh_max_age()
    try:
        from apps.accounts.claim_tokens import ClaimRefreshToken

        token = ClaimRefreshToken(refresh_token)
        max_age = max(0, int(token["exp"]) - int(__import__("time").time()))
    except Exception:
        pass
    response.set_cookie(
        settings.AUTH_REFRESH_COOKIE,
        str(refresh_token),
        max_age=max_age,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path=settings.AUTH_COOKIE_PATH,
    )


def clear_refresh_cookies(response):
    response.delete_cookie(settings.AUTH_REFRESH_COOKIE, path=settings.AUTH_COOKIE_PATH)


def _origin_allowed(raw, surface=None):
    """Exact scheme://host[:port] match against the allowlist (no prefix bypass).

    re-review fix: `startswith` accepted `http://localhost:5000.evil.test`. Parse the
    Origin/Referer and compare the exact scheme+netloc."""
    if not raw:
        return False
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return False
    candidate = f"{parts.scheme}://{parts.netloc}"
    if parts.scheme == "http" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return False
    # Only static CORS origins or registered STAFF-console origins may pass the refresh/logout
    # CSRF check — NOT public/integration origins (Makerspace.cors_allowed_origins), which could
    # otherwise read a staff access token via /auth/refresh.
    if surface == "staff":
        return staff_origin_is_registered(candidate)
    if surface == "member":
        return member_origin_is_registered(candidate)
    return candidate in set(settings.CORS_ALLOWED_ORIGINS) or staff_origin_is_registered(candidate)


def assert_csrf(request, *, surface=None):
    """CSRF guard for cookie-bearing endpoints - refresh & logout (review fixes #1, #8).

    Requires the custom header to be PRESENT (a non-simple header forces a CORS preflight
    that an attacker origin cannot pass) AND the Origin/Referer to exactly match an
    allowlisted origin. No readable cookie is needed, so this works across separate origins."""
    if settings.AUTH_REFRESH_CSRF_HEADER not in request.headers:
        raise PermissionDenied("Missing CSRF header.")
    origin = request.headers.get("Origin") or request.headers.get("Referer", "")
    if not _origin_allowed(origin, surface=surface):
        raise PermissionDenied("Origin not allowed.")
