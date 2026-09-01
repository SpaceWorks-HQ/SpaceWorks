"""Single authority for claim-reachable paths and their per-method policies."""

from apps.accounts.claim_route_types import (
    Allowed,
    AnonymousRead,
    BODY_OBJECT,
    ControlRoute,
    ID,
    LocallyFiltered,
    PUBLIC_TOKEN,
    ReadOnly,
    Refused,
    RowOwnership,
    SLUG,
)
from apps.accounts.claim_routes_auth import AUTH_CLAIM_ROUTES
from apps.accounts.claim_routes_member import MEMBER_CLAIM_ROUTES
from apps.accounts.claim_routes_public import PUBLIC_CLAIM_ROUTES


CLAIM_REACHABLE_PREFIXES = (
    "/api/v1/auth/",
    "/api/v1/member/",
    "/api/v1/memberships/",
    "/api/v1/public/",
)


CLAIM_ROUTES = {
    **PUBLIC_CLAIM_ROUTES,
    **MEMBER_CLAIM_ROUTES,
    **AUTH_CLAIM_ROUTES,
}


def policy_for(view_name, method):
    """Fail closed at runtime even before the build guard reports route drift."""
    return CLAIM_ROUTES.get(
        (view_name, method.upper()),
        Refused("unclassified claim route"),
    )


__all__ = (
    "Allowed",
    "AnonymousRead",
    "BODY_OBJECT",
    "CLAIM_REACHABLE_PREFIXES",
    "CLAIM_ROUTES",
    "ControlRoute",
    "ID",
    "LocallyFiltered",
    "PUBLIC_TOKEN",
    "ReadOnly",
    "Refused",
    "RowOwnership",
    "SLUG",
    "policy_for",
)
