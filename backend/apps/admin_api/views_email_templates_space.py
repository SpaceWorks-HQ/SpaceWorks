from django.http import Http404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.audit import services as audit
from apps.integrations.email_templates import render_preview
from apps.integrations.email_templates_registry import REGISTRY
from apps.integrations.models import EmailTemplate
from apps.openapi_errors import errors

from .serializers_email_templates import EmailTemplateErrorSerializer

from .views_email_templates_common import (
    EmailTemplateDetailSerializer,
    EmailTemplateListItemSerializer,
    EmailTemplatePreviewRequestSerializer,
    EmailTemplatePreviewResponseSerializer,
    EmailTemplateUpdateSerializer,
    _list_payload,
    _require_space_default,
    _resolve_makerspace,
    _resolve_type,
    _space_detail_payload,
    _visible_streams,
)


ERROR_RESPONSES = {
    code: OpenApiResponse(EmailTemplateErrorSerializer, description=description)
    for code, description in (
        (400, "Invalid template or devices module disabled."),
        (401, "Authentication required."),
        (403, "Active staff authority required."),
        (404, "Template or makerspace outside scope, or unknown template."),
        (423, "Makerspace frozen for tenant migration."),
    )
}


@extend_schema(tags=["Email templates"])
class EmailTemplateListView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "head", "options"]

    @extend_schema(
        responses={
            200: EmailTemplateListItemSerializer(many=True),
            **errors(401, 403, 404),
        }
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        streams = _visible_streams(request.user, makerspace_id)
        if not streams:
            raise Http404
        makerspace = _resolve_makerspace(request.user, makerspace_id, streams[0])
        return Response(EmailTemplateListItemSerializer(
            _list_payload(request.user, makerspace, streams), many=True
        ).data)


class SpaceTemplateMixin:
    def _resolve_template(self, request, makerspace_id, stream, audience, key):
        if (stream, audience, key) not in REGISTRY:
            raise Http404
        makerspace = _resolve_makerspace(request.user, makerspace_id, stream)
        _require_space_default(request.user, makerspace_id, stream)
        return makerspace


@extend_schema(tags=["Email templates"])
class EmailTemplateDetailView(SpaceTemplateMixin, APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    @extend_schema(responses={200: EmailTemplateDetailSerializer, **errors(401, 403, 404)})
    def get(self, request, makerspace_id, stream, audience, key, *args, **kwargs):
        makerspace = self._resolve_template(request, makerspace_id, stream, audience, key)
        return Response(EmailTemplateDetailSerializer(
            _space_detail_payload(makerspace, stream, audience, key)
        ).data)

    @extend_schema(
        request=EmailTemplateUpdateSerializer,
        responses={200: EmailTemplateDetailSerializer, **errors(400, 401, 403, 404)},
    )
    def patch(self, request, makerspace_id, stream, audience, key, *args, **kwargs):
        makerspace = self._resolve_template(request, makerspace_id, stream, audience, key)
        payload = EmailTemplateUpdateSerializer(data=request.data, context={
            "stream": stream, "audience": audience, "key": key
        })
        payload.is_valid(raise_exception=True)
        EmailTemplate.objects.update_or_create(
            makerspace=makerspace, stream=stream, audience=audience, key=key,
            defaults=payload.validated_data,
        )
        audit.record(request.user, "email_template.updated", makerspace=makerspace,
                     target=makerspace, meta={"stream": stream, "audience": audience, "key": key})
        return Response(EmailTemplateDetailSerializer(
            _space_detail_payload(makerspace, stream, audience, key)
        ).data)


@extend_schema(tags=["Email templates"])
class EmailTemplateResetView(SpaceTemplateMixin, APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["post", "options"]

    @extend_schema(
        request=None,
        responses={200: EmailTemplateDetailSerializer, **errors(401, 403, 404)},
    )
    def post(self, request, makerspace_id, stream, audience, key, *args, **kwargs):
        makerspace = self._resolve_template(request, makerspace_id, stream, audience, key)
        EmailTemplate.objects.filter(makerspace=makerspace, stream=stream,
                                     audience=audience, key=key).delete()
        audit.record(request.user, "email_template.reset", makerspace=makerspace,
                     target=makerspace, meta={"stream": stream, "audience": audience, "key": key})
        return Response(EmailTemplateDetailSerializer(
            _space_detail_payload(makerspace, stream, audience, key)
        ).data)


@extend_schema(tags=["Email templates"])
class EmailTemplatePreviewView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["post", "options"]

    @extend_schema(request=EmailTemplatePreviewRequestSerializer,
                   responses={200: EmailTemplatePreviewResponseSerializer,
                              **errors(400, 401, 403, 404)})
    def post(self, request, makerspace_id, *args, **kwargs):
        payload = EmailTemplatePreviewRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        makerspace = _resolve_makerspace(request.user, makerspace_id, data["stream"])
        machine_type_id = data.get("machine_type_id")
        if machine_type_id is None:
            _require_space_default(request.user, makerspace_id, data["stream"])
        else:
            _resolve_type(request.user, makerspace, data["stream"], data["audience"],
                          data["key"], machine_type_id)
        return Response(render_preview(data["stream"], data["audience"], data["key"],
                                       data["subject"], data["text_body"], data["html_body"]))
