"""Space-manager archive-recipient enrollment and custody lifecycle API."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.backup import recipients
from apps.backup.models import MakerspaceArchiveRecipient
from apps.backup.serializers_recipients import (
    ArchiveRecipientChallengeSerializer,
    ArchiveRecipientCreateSerializer,
    ArchiveRecipientErrorSerializer,
    ArchiveRecipientSerializer,
    ArchiveRecipientVerifySerializer,
)
from apps.backup.throttles import ArchiveRecipientVerificationThrottle
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


def _makerspace(request, makerspace_id):
    require_action(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace_id)
    return get_object_or_404(Makerspace, pk=makerspace_id)


def _recipient(request, makerspace_id, pk):
    _makerspace(request, makerspace_id)
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


class ArchiveRecipientListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Backup recipients"],
        summary="List archive recipients for a makerspace",
        responses={
            200: ArchiveRecipientSerializer(many=True),
            404: NOT_FOUND,
            **AUTH_ERRORS,
        },
    )
    def get(self, request, makerspace_id):
        makerspace = _makerspace(request, makerspace_id)
        rows = MakerspaceArchiveRecipient.objects.filter(makerspace=makerspace).order_by(
            "pk"
        )
        return Response(ArchiveRecipientSerializer(rows, many=True).data)

    @extend_schema(
        tags=["Backup recipients"],
        summary="Enroll an archive recipient and issue a custody challenge",
        description=(
            "The decrypted challenge is a 32-byte nonce exchanged as canonical, "
            "unpadded base64url. Only the SHA-256 digest of the raw 32 nonce bytes "
            "is persisted."
        ),
        request=ArchiveRecipientCreateSerializer,
        responses={
            201: ArchiveRecipientChallengeSerializer,
            400: INVALID,
            404: NOT_FOUND,
            409: INVALID,
            503: OpenApiResponse(
                response=ArchiveRecipientErrorSerializer,
                description="The age challenge could not be encrypted.",
            ),
            **AUTH_ERRORS,
        },
    )
    def post(self, request, makerspace_id):
        makerspace = _makerspace(request, makerspace_id)
        payload = ArchiveRecipientCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            recipient, encrypted = recipients.enroll_recipient_with_challenge(
                makerspace=makerspace,
                added_by=request.user,
                **payload.validated_data,
            )
        except DjangoValidationError as exc:
            return _validation_response(exc)
        except recipients.RecipientChallengeUnavailable:
            return Response(
                {
                    "detail": "The recipient challenge could not be encrypted.",
                    "code": "challenge_unavailable",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            _challenge_payload(recipient, encrypted),
            status=status.HTTP_201_CREATED,
        )


class ArchiveRecipientVerifyView(APIView):
    permission_classes = [IsActiveStaff]
    throttle_classes = [ArchiveRecipientVerificationThrottle]
    throttle_scope = "archive_recipient_verify"

    def check_permissions(self, request):
        super().check_permissions(request)
        self.recipient = _recipient(
            request, self.kwargs["makerspace_id"], self.kwargs["pk"]
        )

    @extend_schema(
        tags=["Backup recipients"],
        summary="Verify possession of an archive recipient",
        description=(
            "Submit the decrypted nonce as canonical unpadded base64url. It must "
            "decode to exactly 32 bytes; padding and non-canonical forms are refused."
        ),
        request=ArchiveRecipientVerifySerializer,
        responses={
            200: ArchiveRecipientSerializer,
            400: INVALID,
            409: INVALID,
            404: NOT_FOUND,
            429: OpenApiResponse(
                response=ArchiveRecipientErrorSerializer,
                description="Verification attempts for this recipient are throttled.",
            ),
            **AUTH_ERRORS,
        },
    )
    def post(self, request, makerspace_id, pk):
        payload = ArchiveRecipientVerifySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            recipient = recipients.verify_recipient(
                recipient_id=self.recipient.pk,
                makerspace_id=makerspace_id,
                submitted_nonce=payload.validated_data["nonce"],
                actor=request.user,
            )
        except DjangoValidationError as exc:
            return _validation_response(exc)
        except MakerspaceArchiveRecipient.DoesNotExist as exc:
            raise Http404 from exc
        return Response(ArchiveRecipientSerializer(recipient).data)


class ArchiveRecipientReissueView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Backup recipients"],
        summary="Reissue an archive-recipient custody challenge",
        description=(
            "The decrypted 32-byte nonce is exchanged as canonical, unpadded "
            "base64url. The prior challenge stops verifying when this request commits."
        ),
        request=None,
        responses={
            200: ArchiveRecipientChallengeSerializer,
            400: INVALID,
            404: NOT_FOUND,
            503: OpenApiResponse(
                response=ArchiveRecipientErrorSerializer,
                description="The age challenge could not be encrypted.",
            ),
            **AUTH_ERRORS,
        },
    )
    def post(self, request, makerspace_id, pk):
        recipient = _recipient(request, makerspace_id, pk)
        try:
            recipient, encrypted = recipients.reissue_recipient_challenge(
                recipient=recipient, actor=request.user
            )
        except DjangoValidationError as exc:
            return _validation_response(exc)
        except MakerspaceArchiveRecipient.DoesNotExist as exc:
            raise Http404 from exc
        except recipients.RecipientChallengeUnavailable:
            return Response(
                {
                    "detail": "The recipient challenge could not be encrypted.",
                    "code": "challenge_unavailable",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(_challenge_payload(recipient, encrypted))


class ArchiveRecipientLifecycleView(APIView):
    permission_classes = [IsActiveStaff]
    operation = None

    def post(self, request, makerspace_id, pk):
        recipient = _recipient(request, makerspace_id, pk)
        try:
            recipient = self.operation(recipient=recipient, actor=request.user)
        except DjangoValidationError as exc:
            return _validation_response(exc)
        except MakerspaceArchiveRecipient.DoesNotExist as exc:
            raise Http404 from exc
        return Response(ArchiveRecipientSerializer(recipient).data)


@extend_schema_view(
    post=extend_schema(
        tags=["Backup recipients"],
        summary="Revoke an archive recipient",
        request=None,
        responses=LIFECYCLE_RESPONSES,
    )
)
class ArchiveRecipientRevokeView(ArchiveRecipientLifecycleView):
    operation = staticmethod(recipients.revoke_recipient)


@extend_schema_view(
    post=extend_schema(
        tags=["Backup recipients"],
        summary="Mark an archive recipient as compromised",
        request=None,
        responses=LIFECYCLE_RESPONSES,
    )
)
class ArchiveRecipientCompromiseView(ArchiveRecipientLifecycleView):
    operation = staticmethod(recipients.compromise_recipient)


@extend_schema_view(
    post=extend_schema(
        tags=["Backup recipients"],
        summary="Reactivate a revoked archive recipient",
        request=None,
        responses=LIFECYCLE_RESPONSES,
    )
)
class ArchiveRecipientReactivateView(ArchiveRecipientLifecycleView):
    operation = staticmethod(recipients.reactivate_recipient)
