"""Claim policies for the authentication surface."""

from apps.accounts.claim_route_types import AnonymousRead, ControlRoute, Refused


def _refused(name, methods, reason):
    return {
        **{(name, method): Refused(reason) for method in methods},
        (name, "OPTIONS"): AnonymousRead(),
    }


AUTH_CLAIM_ROUTES = {
    **_refused("social-nonce", ("POST",), "claim sessions cannot start identity linking"),
    **_refused("social-google", ("POST",), "claim sessions cannot change identity"),
    **_refused("social-apple", ("POST",), "claim sessions cannot change identity"),
    **_refused("social-oidc", ("POST",), "claim sessions cannot change identity"),
    ("social-providers", "GET"): AnonymousRead(),
    ("social-providers", "HEAD"): AnonymousRead(),
    **_refused("social-providers", ("POST",), "claim sessions cannot link identity providers"),
    **_refused(
        "social-provider-detail",
        ("DELETE",),
        "claim sessions cannot unlink identity providers",
    ),
    **_refused(
        "device-attestation-challenge",
        ("POST",),
        "claim sessions cannot create device grants",
    ),
    **_refused("device-login", ("POST",), "claim sessions cannot create device grants"),
    **_refused("device-refresh", ("POST",), "claim sessions cannot use device refresh families"),
    **_refused("device-logout", ("POST",), "claim sessions cannot mutate device grants"),
    **_refused("device-grants", ("GET", "HEAD"), "claim sessions cannot enumerate device grants"),
    **_refused("device-grant-detail", ("DELETE",), "claim sessions cannot revoke device grants"),
    **_refused("auth-phone-login-start", ("POST",), "claim sessions cannot change login identity"),
    **_refused(
        "auth-phone-login-confirm",
        ("POST",),
        "claim sessions cannot change login identity",
    ),
    **_refused("auth-phone-link-start", ("POST",), "claim sessions cannot change login identity"),
    **_refused("auth-phone-link-confirm", ("POST",), "claim sessions cannot change login identity"),
    **_refused("auth-phone-unlink", ("DELETE",), "claim sessions cannot change login identity"),
    **_refused("auth-login", ("POST",), "claim sessions do not authenticate with passwords"),
    ("auth-claim-redeem", "POST"): ControlRoute(),
    ("auth-claim-redeem", "OPTIONS"): AnonymousRead(),
    ("auth-refresh", "POST"): ControlRoute(),
    ("auth-refresh", "OPTIONS"): AnonymousRead(),
    ("auth-logout", "POST"): ControlRoute(),
    ("auth-logout", "OPTIONS"): AnonymousRead(),
    ("auth-me", "GET"): ControlRoute(),
    ("auth-me", "HEAD"): ControlRoute(),
    ("auth-me", "OPTIONS"): AnonymousRead(),
    **_refused("auth-change-password", ("POST",), "walk-ins have no password credential"),
    **_refused("auth-forgot-password", ("POST",), "walk-ins have no password credential"),
    **_refused("auth-reset-password", ("POST",), "walk-ins have no password credential"),
    **_refused("auth-member-sign-up", ("POST",), "claim sessions cannot create another account"),
    **_refused("auth-email-verification-resend", ("POST",), "walk-ins cannot verify email"),
    **_refused("auth-email-verification-confirm", ("POST",), "walk-ins cannot verify email"),
}
