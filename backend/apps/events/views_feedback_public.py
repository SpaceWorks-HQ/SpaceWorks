from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import NotAuthenticated, NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.events.throttles import PublicFeedbackRateThrottle
from apps.events.models import Event, EventFeedbackSurvey
from apps.events.serializers_feedback import (
    FeedbackFormSerializer,
    FeedbackSubmissionResponseSerializer,
    FeedbackSubmissionSerializer,
)
from apps.events.services_feedback import (
    submit_anonymous_feedback,
    submit_identified_feedback,
)
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.guards import require_module_for_servable
from apps.makerspaces.lookup import get_public_makerspace


ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid feedback answers."),
    401: OpenApiResponse(ErrorSerializer, description="Authentication is required for a certificate."),
    404: OpenApiResponse(ErrorSerializer, description="Feedback form not found."),
    409: OpenApiResponse(ErrorSerializer, description="Feedback retry conflict."),
    429: OpenApiResponse(ErrorSerializer, description="Rate limit exceeded."),
}


def _public_feedback_event(makerspace, token):
    event = get_object_or_404(
        Event.objects.select_related("makerspace").filter(
            makerspace=makerspace,
            public_token=token,
            is_public=True,
            status__in=(Event.Status.PUBLISHED, Event.Status.COMPLETED),
            ends_at__lte=timezone.now(),
        )
    )
    survey = EventFeedbackSurvey.objects.filter(event=event, is_open=True).first()
    if survey is None:
        raise NotFound()
    return event, survey


def feedback_form_payload(event, survey, *, certificate=None):
    return {
        "event": {
            "public_token": str(event.public_token),
            "title": event.title,
            "starts_at": event.starts_at,
            "ends_at": event.ends_at,
        },
        "survey": survey,
        "mode": "certificate" if survey.certificate_enabled else "anonymous",
        "requires_auth": survey.certificate_enabled,
        "certificate": certificate,
    }


class PublicEventFeedbackView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [PublicFeedbackRateThrottle]

    @extend_schema(tags=["Public events"], auth=[], responses={200: FeedbackFormSerializer, **ERRORS})
    def get(self, request, makerspace_slug, public_token):
        makerspace = get_public_makerspace(makerspace_slug)
        require_module_for_servable(makerspace, "events")
        event, survey = _public_feedback_event(makerspace, public_token)
        return Response(FeedbackFormSerializer(feedback_form_payload(event, survey)).data)

    @extend_schema(tags=["Public events"], auth=[{"jwtAuth": []}, {}], request=FeedbackSubmissionSerializer, responses={201: FeedbackSubmissionResponseSerializer, **ERRORS})
    def post(self, request, makerspace_slug, public_token):
        makerspace = get_public_makerspace(makerspace_slug)
        require_module_for_servable(makerspace, "events")
        event, survey = _public_feedback_event(makerspace, public_token)
        serializer = FeedbackSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if survey.certificate_enabled:
            if not request.user.is_authenticated:
                raise NotAuthenticated()
            if "email" not in data:
                raise ValidationError({"email": "This field is required."})
            _response, certificate = submit_identified_feedback(
                event,
                actor=request.user,
                email=data["email"],
                answers=data["answers"],
            )
        else:
            if "email" in data:
                raise ValidationError({"email": "Email is not accepted for anonymous feedback."})
            _response, certificate = submit_anonymous_feedback(event, data["answers"])
        payload = {"thank_you_text": survey.thank_you_text, "certificate": certificate}
        return Response(FeedbackSubmissionResponseSerializer(payload).data, status=201)
