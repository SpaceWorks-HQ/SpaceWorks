import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiResponse
from rest_framework import status
from rest_framework.exceptions import ValidationError as DrfValidationError
from rest_framework.response import Response

from .gate_errors import SourceMigrationGateError
from .insertion_errors import TenantInsertionError
from .preflight import SourcePreflightError
from .protocol_errors import TenantMigrationProtocolError
from .serializers import FieldValidationErrorSerializer, TypedErrorSerializer

logger = logging.getLogger(__name__)

AUTH_ERRORS = {
    401: OpenApiResponse(response=TypedErrorSerializer, description="Authentication required."),
    403: OpenApiResponse(response=TypedErrorSerializer, description="Superadmin access required."),
    429: OpenApiResponse(response=TypedErrorSerializer, description="Throttle limit exceeded."),
    500: OpenApiResponse(response=TypedErrorSerializer, description="Unexpected migration failure."),
}
NOT_FOUND = OpenApiResponse(response=TypedErrorSerializer, description="Not found.")
CONFLICT = OpenApiResponse(response=TypedErrorSerializer, description="State conflict.")
FIELD_ERRORS = OpenApiResponse(
    response=FieldValidationErrorSerializer, description="Field-keyed validation errors."
)


def protocol_error(exc):
    if isinstance(exc, SourceMigrationGateError):
        return Response(
            {
                "detail": str(exc),
                "code": getattr(exc, "code", "tenant_migration_gate_conflict"),
            },
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, TenantMigrationProtocolError):
        code = getattr(exc, "code", "tenant_migration_conflict")
        return Response(
            {"detail": str(exc), "code": code}, status=status.HTTP_409_CONFLICT
        )
    if isinstance(exc, TenantInsertionError):
        return Response(
            {"detail": str(exc), "code": "invalid_archive"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if isinstance(exc, SourcePreflightError):
        return Response(
            {"detail": str(exc), "code": "source_preflight_failed"},
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, PermissionError):
        return Response(
            {"detail": str(exc), "code": "permission_denied"},
            status=status.HTTP_403_FORBIDDEN,
        )
    if not isinstance(exc, (DjangoValidationError, DrfValidationError, ValueError)):
        logger.error(
            "tenant_migration_api_failed",
            extra={"exception_type": type(exc).__name__},
        )
        return Response(
            {"detail": "The tenant migration request failed unexpectedly.", "code": "internal_error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code = "invalid_request"
    detail = str(exc)
    drf_detail = getattr(exc, "detail", None)
    if isinstance(drf_detail, dict) and "detail" in drf_detail:
        detail = str(drf_detail["detail"])
    elif isinstance(exc, DjangoValidationError):
        values = getattr(exc, "message_dict", {}).get("detail", ())
        if values:
            detail = str(values[0])
    return Response(
        {"detail": detail, "code": code}, status=status.HTTP_400_BAD_REQUEST
    )
