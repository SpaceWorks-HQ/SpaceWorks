from drf_spectacular.utils import OpenApiResponse

from apps.hardware_requests.exceptions import ErrorSerializer
from apps.hardware_requests.models import HardwareRequest

ERROR_400 = OpenApiResponse(ErrorSerializer, description="Invalid request.")
ERROR_401 = OpenApiResponse(ErrorSerializer, description="Authentication required.")
ERROR_403 = OpenApiResponse(ErrorSerializer, description="Permission denied.")
ERROR_404 = OpenApiResponse(ErrorSerializer, description="Not found.")
ERROR_409 = OpenApiResponse(ErrorSerializer, description="Workflow conflict.")
ERROR_429 = OpenApiResponse(ErrorSerializer, description="Too many requests.")
ERROR_503 = OpenApiResponse(ErrorSerializer, description="Service unavailable.")

PUBLIC_ERROR_RESPONSES = {
    400: ERROR_400,
    401: ERROR_401,
    403: ERROR_403,
    404: ERROR_404,
    409: ERROR_409,
    429: ERROR_429,
    503: ERROR_503,
}
ADMIN_LIST_ERROR_RESPONSES = {
    403: ERROR_403,
    404: ERROR_404,
}
ACTION_ERROR_RESPONSES = {
    400: ERROR_400,
    403: ERROR_403,
    404: ERROR_404,
    409: ERROR_409,
}


def request_queryset():
    return HardwareRequest.objects.select_related(
        "makerspace",
        "requester",
        "accepted_by",
        "assigned_box",
        "issued_by",
        "issue_evidence",
    ).prefetch_related("items__product", "items__asset_links__asset", "returnevent_set")


# The `guest-admin/` routes REUSE the admin view classes (`ActiveLoansView`,
# `ReturnRequestView`), so the module a request must satisfy depends on the URL SURFACE it
# arrived through, not on the view class. Gating the shared view on `guest_handover`
# instead let an OPTIONAL module block the CORE reviewed-request transitions for every
# actor -- a core-only install reached `accepted` and could never issue or return the
# hardware, which is the `9e496997` bug class one module over. `guest_handover` is the
# narrow guest-admin SURFACE, never the underlying authority: that is `rbac.Action`.
#
# Declared as a table for the same reason as `CHANNEL_MODULE_KEYS` -- one gate shared by
# several call sites, where the table IS the enforcement declaration the registry drift
# guard reads.
HANDOVER_SURFACE_MODULE_KEYS = {
    "guest-admin": "guest_handover",
    "admin": "request_workflow",
}


def handover_surface_module(request):
    """Which module key gates this reviewed-request call, by the URL it came through."""
    match = getattr(request, "resolver_match", None)
    url_name = getattr(match, "url_name", None) or ""
    surface = "guest-admin" if url_name.startswith("guest-admin-") else "admin"
    return HANDOVER_SURFACE_MODULE_KEYS[surface]
