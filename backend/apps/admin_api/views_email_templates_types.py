from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.audit import services as audit
from apps.integrations.models import MachineTypeEmailTemplate

from .views_email_templates_common import (
    EmailTemplateDetailSerializer,
    EmailTemplateUpdateSerializer,
    _resolve_makerspace,
    _resolve_type,
    _type_detail_payload,
)


class TypeTemplateMixin:
    def _resolve_template(self, request, makerspace_id, stream, audience, key, machine_type_id):
        makerspace = _resolve_makerspace(request.user, makerspace_id, stream)
        machine_type = _resolve_type(
            request.user, makerspace, stream, audience, key, machine_type_id
        )
        return makerspace, machine_type


@extend_schema(tags=["Email templates"])
class MachineTypeEmailTemplateDetailView(TypeTemplateMixin, APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    @extend_schema(responses={200: EmailTemplateDetailSerializer})
    def get(self, request, makerspace_id, stream, audience, key, machine_type_id, *args, **kwargs):
        makerspace, machine_type = self._resolve_template(
            request, makerspace_id, stream, audience, key, machine_type_id
        )
        return Response(EmailTemplateDetailSerializer(
            _type_detail_payload(makerspace, machine_type, stream, audience, key)
        ).data)

    @extend_schema(request=EmailTemplateUpdateSerializer, responses={200: EmailTemplateDetailSerializer})
    def patch(self, request, makerspace_id, stream, audience, key, machine_type_id, *args, **kwargs):
        makerspace, machine_type = self._resolve_template(
            request, makerspace_id, stream, audience, key, machine_type_id
        )
        payload = EmailTemplateUpdateSerializer(data=request.data, context={
            "stream": stream, "audience": audience, "key": key
        })
        payload.is_valid(raise_exception=True)
        MachineTypeEmailTemplate.objects.update_or_create(
            makerspace=makerspace, machine_type=machine_type, stream=stream,
            audience=audience, key=key, defaults=payload.validated_data,
        )
        meta = {"stream": stream, "audience": audience, "key": key,
                "machine_type_id": machine_type.pk}
        audit.record(request.user, "email_template.type_updated", makerspace=makerspace,
                     target=machine_type, meta=meta)
        return Response(EmailTemplateDetailSerializer(
            _type_detail_payload(makerspace, machine_type, stream, audience, key)
        ).data)


@extend_schema(tags=["Email templates"])
class MachineTypeEmailTemplateResetView(TypeTemplateMixin, APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["post", "options"]

    @extend_schema(request=None, responses={200: EmailTemplateDetailSerializer})
    def post(self, request, makerspace_id, stream, audience, key, machine_type_id, *args, **kwargs):
        makerspace, machine_type = self._resolve_template(
            request, makerspace_id, stream, audience, key, machine_type_id
        )
        MachineTypeEmailTemplate.objects.filter(
            makerspace=makerspace, machine_type=machine_type, stream=stream,
            audience=audience, key=key,
        ).delete()
        meta = {"stream": stream, "audience": audience, "key": key,
                "machine_type_id": machine_type.pk}
        audit.record(request.user, "email_template.type_reset", makerspace=makerspace,
                     target=machine_type, meta=meta)
        return Response(EmailTemplateDetailSerializer(
            _type_detail_payload(makerspace, machine_type, stream, audience, key)
        ).data)
