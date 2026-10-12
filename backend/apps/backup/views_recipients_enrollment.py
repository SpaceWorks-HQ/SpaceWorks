"""Recipient enrollment and possession challenges."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.backup import recipients
from apps.backup.models import MakerspaceArchiveRecipient
from apps.backup.serializers_recipients import (
    ArchiveRecipientChallengeSerializer, ArchiveRecipientCreateSerializer,
    ArchiveRecipientErrorSerializer, ArchiveRecipientSerializer, ArchiveRecipientVerifySerializer,
)
from apps.backup.throttles import ArchiveRecipientVerificationThrottle
from apps.backup.views_recipients_common import (
    AUTH_ERRORS, INVALID, NOT_FOUND,
    _challenge_payload, _makerspace, _recipient, _validation_response,
)


class ArchiveRecipientListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Backup recipients"],
        summary="List archive recipients for a makerspace",
        responses={
            200: ArchiveRecipientSerializer(many=True),
            400: INVALID,
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


