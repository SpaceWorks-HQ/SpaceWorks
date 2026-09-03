from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.events import services
from apps.events.certificate_storage import CertificateStorageUnavailable
from apps.events.models import EventAttendanceCertificate, EventFeedbackSurvey
from apps.events.organizer_authority import can_manage_event, organizer_event_q
from apps.events.serializers_admin import EmptyActionSerializer
from apps.events.serializers_feedback import (
    AttendanceCorrectionResponseSerializer,
    CertificateDownloadSerializer,
    CertificateRevokeSerializer,
    CertificateSummarySerializer,
    FeedbackResponseListSerializer,
    FeedbackResponseSerializer,
    FeedbackSurveyAdminEnvelopeSerializer,
    FeedbackSurveySerializer,
    FeedbackSurveyWriteSerializer,
)
from apps.events.services_certificates import download_url, reissue, revoke
from apps.events.services_feedback import close_survey, configure_survey, open_survey
from apps.events.views_admin_events import _manageable_event, _manageable_registration
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module


ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid request."),
    403: OpenApiResponse(ErrorSerializer, description="Event management is required."),
    404: OpenApiResponse(ErrorSerializer, description="Event resource not found."),
    409: OpenApiResponse(ErrorSerializer, description="Event state conflict."),
}


def _manageable_certificate(actor, pk):
    scoped = rbac.scope_by_visibility_or_action(
        actor,
        rbac.Action.MANAGE_EVENTS,
        EventAttendanceCertificate.objects.all(),
        field="registration__event__makerspace_id",
    )
    certificate = get_object_or_404(
        EventAttendanceCertificate.objects.select_related(
            "registration__event__makerspace", "response",
        ).filter(
            Q(pk__in=scoped.values("pk"))
            | organizer_event_q(actor, event_prefix="registration__event__")
        ).distinct(),
        pk=pk,
    )
    require_module(certificate.registration.event.makerspace, "events")
    if not can_manage_event(actor, certificate.registration.event):
        raise PermissionDenied()
    return certificate


class EventFeedbackSurveyView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin events"], responses={200: FeedbackSurveyAdminEnvelopeSerializer, **ERRORS})
    def get(self, request, pk):
        event = _manageable_event(request.user, pk)
        survey = getattr(event, "feedback_survey", None)
        if survey is not None:
            survey.response_count = survey.responses.count()
        return Response({"survey": None if survey is None else FeedbackSurveySerializer(survey).data})

    @extend_schema(tags=["Admin events"], request=FeedbackSurveyWriteSerializer, responses={200: FeedbackSurveySerializer, **ERRORS})
    def put(self, request, pk):
        event = _manageable_event(request.user, pk)
        serializer = FeedbackSurveyWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        survey = configure_survey(event, actor=request.user, **serializer.validated_data)
        survey.response_count = survey.responses.count()
        return Response(FeedbackSurveySerializer(survey).data)


class _SurveyActionView(APIView):
    permission_classes = [IsActiveStaff]
    operation = None

    def execute(self, request, pk):
        event = _manageable_event(request.user, pk)
        EmptyActionSerializer(data=request.data).is_valid(raise_exception=True)
        survey = self.operation(event, actor=request.user)
        survey.response_count = survey.responses.count()
        return Response(FeedbackSurveySerializer(survey).data)


class EventFeedbackSurveyOpenView(_SurveyActionView):
    operation = staticmethod(open_survey)

    @extend_schema(tags=["Admin events"], request=EmptyActionSerializer, responses={200: FeedbackSurveySerializer, **ERRORS})
    def post(self, request, pk):
        return self.execute(request, pk)


class EventFeedbackSurveyCloseView(_SurveyActionView):
    operation = staticmethod(close_survey)

    @extend_schema(tags=["Admin events"], request=EmptyActionSerializer, responses={200: FeedbackSurveySerializer, **ERRORS})
    def post(self, request, pk):
        return self.execute(request, pk)


class EventFeedbackResponseListView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin events"], responses={200: FeedbackResponseListSerializer, **ERRORS})
    def get(self, request, pk):
        event = _manageable_event(request.user, pk)
        survey = get_object_or_404(EventFeedbackSurvey, event=event)
        queryset = survey.responses.select_related("registration").prefetch_related("certificates").order_by("created_at", "id")
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(FeedbackResponseSerializer(page, many=True).data)


class EventRegistrationCorrectAttendanceView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin events"], request=EmptyActionSerializer, responses={200: AttendanceCorrectionResponseSerializer, **ERRORS})
    def post(self, request, pk):
        registration = _manageable_registration(request.user, pk)
        EmptyActionSerializer(data=request.data).is_valid(raise_exception=True)
        corrected, revoked = services.correct_attendance(registration, actor=request.user)
        return Response({"registration_id": corrected.pk, "status": corrected.status, "revoked_certificates": len(revoked)})


class EventCertificateDownloadView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin events"], responses={200: CertificateDownloadSerializer, 410: OpenApiResponse(ErrorSerializer, description="Certificate revoked."), 503: OpenApiResponse(ErrorSerializer, description="Certificate storage unavailable."), **ERRORS})
    def get(self, request, pk):
        certificate = _manageable_certificate(request.user, pk)
        if certificate.status == EventAttendanceCertificate.Status.REVOKED:
            return Response({"detail": "Certificate revoked.", "code": "certificate_revoked"}, status=status.HTTP_410_GONE)
        try:
            certificate, url = download_url(certificate)
        except CertificateStorageUnavailable:
            return Response({"detail": "Certificate storage is unavailable.", "code": "storage_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"url": url, "expires_at": timezone.now() + timedelta(seconds=settings.EVIDENCE_URL_TTL_SECONDS)})


class EventCertificateRevokeView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin events"], request=CertificateRevokeSerializer, responses={200: CertificateSummarySerializer, **ERRORS})
    def post(self, request, pk):
        certificate = _manageable_certificate(request.user, pk)
        serializer = CertificateRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(CertificateSummarySerializer(revoke(certificate, actor=request.user, **serializer.validated_data)).data)


class EventCertificateReissueView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin events"], request=EmptyActionSerializer, responses={201: CertificateSummarySerializer, **ERRORS})
    def post(self, request, pk):
        certificate = _manageable_certificate(request.user, pk)
        EmptyActionSerializer(data=request.data).is_valid(raise_exception=True)
        created = reissue(certificate.registration, actor=request.user)
        return Response(CertificateSummarySerializer(created).data, status=status.HTTP_201_CREATED)
