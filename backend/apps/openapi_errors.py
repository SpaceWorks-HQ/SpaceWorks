"""Reusable OpenAPI error responses for `extend_schema(responses=...)`.

The repo rule is that every route documents its error responses, and 151 operations
documented none -- most often because each view would have had to spell out the same five
`OpenApiResponse(description=...)` lines again. `errors(400, 403)` returns exactly the
codes a view really answers, so the schema stays a statement about the view rather than a
blanket list every route copies.
"""

from drf_spectacular.utils import OpenApiResponse

_DESCRIPTIONS = {
    400: "Validation failed, or the makerspace module this route belongs to is off.",
    401: "Not signed in.",
    403: "Signed in, but this action or makerspace is not permitted (or the secret is wrong).",
    404: "Not found, not visible to this actor, or the surface is not enabled here.",
    409: "Conflicts with the current state.",
    415: "Unsupported media type for the request body.",
    423: "Makerspace writes are frozen for tenant migration.",
    429: "Rate limit exceeded; retry after the interval in Retry-After.",
    503: "A required dependency is unavailable.",
}


def errors(*codes, **overrides):
    """`{code: OpenApiResponse}` for each code; `overrides` maps `e404="..."` to a description."""
    out = {}
    for code in codes:
        description = overrides.get(f"e{code}", _DESCRIPTIONS[code])
        out[code] = OpenApiResponse(description=description)
    return out
