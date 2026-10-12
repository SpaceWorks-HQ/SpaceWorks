"""Shared authorization, lookup and error contracts for backup recipients."""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse
from rest_framework.response import Response

from apps.accounts import rbac
from apps.admin_api.permissions import require_action
from apps.backup.models import MakerspaceArchiveRecipient
from apps.backup.module_gate import BACKUP_MODULE_KEY
from apps.backup.serializers_recipients import ArchiveRecipientErrorSerializer, ArchiveRecipientSerializer
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace

AUTH_ERRORS = {
    401: OpenApiResponse(
        response=ArchiveRecipientErrorSerializer,
        description="Authentication is required.",
    ),
    403: OpenApiResponse(
        response=ArchiveRecipientErrorSerializer,
        description="Manage-makerspace permission is required.",
    ),
}
NOT_FOUND = OpenApiResponse(
    response=ArchiveRecipientErrorSerializer,
    description="The recipient does not exist in this makerspace.",
)
INVALID = OpenApiResponse(
    response=ArchiveRecipientErrorSerializer,
    description="The recipient or lifecycle request is invalid.",
)
LIFECYCLE_RESPONSES = {
    200: ArchiveRecipientSerializer,
    400: INVALID,
    404: NOT_FOUND,
    **AUTH_ERRORS,
}


def _makerspace(request, makerspace_id, *, module_gated=True):
    require_action(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace_id)
    makerspace = get_object_or_404(Makerspace, pk=makerspace_id)
    if module_gated:
        require_module(makerspace, BACKUP_MODULE_KEY)
    return makerspace


def _recipient(request, makerspace_id, pk, *, module_gated=True):
    _makerspace(request, makerspace_id, module_gated=module_gated)
    return get_object_or_404(
        MakerspaceArchiveRecipient.objects.filter(makerspace_id=makerspace_id),
        pk=pk,
    )


def _challenge_payload(recipient, encrypted_challenge):
    return {
        "recipient": ArchiveRecipientSerializer(recipient).data,
        "encrypted_challenge": encrypted_challenge,
        "nonce_encoding": "base64url-unpadded",
    }


def _validation_response(exc):
    detail = exc.messages[0] if exc.messages else "The request is invalid."
    code = getattr(exc, "code", None)
    if code is None and getattr(exc, "error_list", None):
        code = exc.error_list[0].code
    status_code = 409 if code == "recipient_reserved" else 400
    return Response(
        {"detail": detail, "code": code or "invalid_request"}, status=status_code
    )


