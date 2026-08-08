from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.audit import services as audit
from apps.integrations.email_templates import render_preview
from apps.integrations.email_templates_registry import (
    REGISTRY,
    get_entry,
    iter_entries,
    validate_email_template_strings,
)
from apps.integrations.models import EmailTemplate
from apps.makerspaces.models import Makerspace

STREAM_ACTIONS = {
    "hardware": (rbac.Action.EDIT_INVENTORY, rbac.Action.MANAGE_MAKERSPACE),
    "printing": (rbac.Action.MANAGE_PRINTING, rbac.Action.MANAGE_MAKERSPACE),
    "events": (rbac.Action.MANAGE_EVENTS, rbac.Action.MANAGE_MAKERSPACE),
    "bookings": (rbac.Action.MANAGE_BOOKINGS, rbac.Action.MANAGE_MAKERSPACE),
    "maintenance": (rbac.Action.MANAGE_MACHINES, rbac.Action.MANAGE_MAKERSPACE),
    # Membership templates carry applicant and member identity, so they are the space
    # manager's alone — there is no narrower action that should reach them.
    "membership": (rbac.Action.MANAGE_MAKERSPACE,),
}

# The module a stream's templates belong to (D14). Editing wording for a feature the space
# does not run is offering a setting that can never fire; `hardware`/`printing` map to
# modules that are core or already gated at their own surfaces.
STREAM_MODULES = {
    "events": "events",
    "bookings": "bookings",
    "maintenance": "maintenance",
    "membership": "membership",
}


def _stream_module_available(makerspace, stream):
    key = STREAM_MODULES.get(stream)
    if key is None:
        return True
    try:
        from apps.makerspaces.platform import module_enabled

        return bool(module_enabled(makerspace, key))
    except Exception:
        # Fail open, matching every other notification capability lookup: a broken check
        # must not hide an editor an operator is entitled to.
        return True


def _resolve_makerspace(actor, makerspace_id, stream):
    actions = STREAM_ACTIONS.get(stream)
    if actions is None:
        raise Http404
    scope = rbac.makerspaces_for_actions(actor, *actions)
    qs = Makerspace.objects.filter(pk=makerspace_id)
    if scope is not rbac.ALL:
        qs = qs.filter(id__in=scope) if scope else qs.none()
    makerspace = qs.first()
    if makerspace is None:
        raise Http404
    if not _stream_module_available(makerspace, stream):
        raise Http404
    return makerspace


def _visible_streams(actor, makerspace_id):
    streams = []
    for stream in STREAM_ACTIONS:
        try:
            _resolve_makerspace(actor, makerspace_id, stream)
        except Http404:
            continue
        streams.append(stream)
    return streams


class EmailTemplateDetailSerializer(serializers.Serializer):
    stream = serializers.CharField(read_only=True)
    audience = serializers.CharField(read_only=True)
    key = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    fields = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField()),
        read_only=True,
    )
    subject = serializers.CharField(read_only=True)
    text_body = serializers.CharField(read_only=True)
    html_body = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_overridden = serializers.BooleanField(read_only=True)
    default_subject = serializers.CharField(read_only=True)
    default_text = serializers.CharField(read_only=True)
    default_html = serializers.CharField(read_only=True)


class EmailTemplateListItemSerializer(serializers.Serializer):
    stream = serializers.CharField(read_only=True)
    audience = serializers.CharField(read_only=True)
    key = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_overridden = serializers.BooleanField(read_only=True)


class EmailTemplateUpdateSerializer(serializers.Serializer):
    subject = serializers.CharField(allow_blank=True, max_length=200)
    text_body = serializers.CharField(allow_blank=True)
    html_body = serializers.CharField(allow_blank=True)
    is_active = serializers.BooleanField()

    def validate(self, attrs):
        try:
            validate_email_template_strings(
                self.context["stream"],
                self.context["audience"],
                self.context["key"],
                attrs["subject"],
                attrs["text_body"],
                attrs["html_body"],
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return attrs


class EmailTemplatePreviewRequestSerializer(serializers.Serializer):
    stream = serializers.CharField()
    audience = serializers.CharField()
    key = serializers.CharField()
    subject = serializers.CharField(allow_blank=True, max_length=200)
    text_body = serializers.CharField(allow_blank=True)
    html_body = serializers.CharField(allow_blank=True)

    def validate(self, attrs):
        try:
            validate_email_template_strings(
                attrs["stream"],
                attrs["audience"],
                attrs["key"],
                attrs["subject"],
                attrs["text_body"],
                attrs["html_body"],
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return attrs


class EmailTemplatePreviewResponseSerializer(serializers.Serializer):
    subject = serializers.CharField(read_only=True)
    text_body = serializers.CharField(read_only=True)
    html_body = serializers.CharField(read_only=True)


def _detail_payload(makerspace, stream, audience, key):
    entry = get_entry(stream, audience, key)
    if entry is None:
        raise Http404
    row = EmailTemplate.objects.filter(
        makerspace=makerspace, stream=stream, audience=audience, key=key
    ).first()
    return {
        "stream": stream,
        "audience": audience,
        "key": key,
        "label": entry.label,
        "description": entry.description,
        "fields": entry.fields,
        "subject": row.subject if row else entry.default_subject,
        "text_body": row.text_body if row else entry.default_text,
        "html_body": row.html_body if row else entry.default_html,
        "is_active": row.is_active if row else True,
        "is_overridden": row is not None,
        "default_subject": entry.default_subject,
        "default_text": entry.default_text,
        "default_html": entry.default_html,
    }


def _list_payload(makerspace, visible_streams):
    rows = {
        (row.stream, row.audience, row.key): row
        for row in EmailTemplate.objects.filter(
            makerspace=makerspace,
            stream__in=visible_streams,
        )
    }
    payload = []
    for (stream, audience, key), entry in iter_entries():
        if stream not in visible_streams:
            continue
        row = rows.get((stream, audience, key))
        payload.append(
            {
                "stream": stream,
                "audience": audience,
                "key": key,
                "label": entry.label,
                "is_active": row.is_active if row else True,
                "is_overridden": row is not None,
            }
        )
    return sorted(payload, key=lambda item: (item["stream"], item["audience"], item["key"]))


@extend_schema(tags=["Email templates"])
class EmailTemplateListView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "head", "options"]

    @extend_schema(responses={200: EmailTemplateListItemSerializer(many=True)})
    def get(self, request, makerspace_id, *args, **kwargs):
        streams = _visible_streams(request.user, makerspace_id)
        if not streams:
            raise Http404
        makerspace = _resolve_makerspace(request.user, makerspace_id, streams[0])
        data = EmailTemplateListItemSerializer(
            _list_payload(makerspace, streams),
            many=True,
        ).data
        return Response(data)


@extend_schema(tags=["Email templates"])
class EmailTemplateDetailView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    def _resolve_template(self, request, makerspace_id, stream, audience, key):
        if stream not in STREAM_ACTIONS or (stream, audience, key) not in REGISTRY:
            raise Http404
        return _resolve_makerspace(request.user, makerspace_id, stream)

    @extend_schema(responses={200: EmailTemplateDetailSerializer})
    def get(self, request, makerspace_id, stream, audience, key, *args, **kwargs):
        makerspace = self._resolve_template(request, makerspace_id, stream, audience, key)
        return Response(
            EmailTemplateDetailSerializer(
                _detail_payload(makerspace, stream, audience, key)
            ).data
        )

    @extend_schema(
        request=EmailTemplateUpdateSerializer,
        responses={200: EmailTemplateDetailSerializer},
    )
    def patch(self, request, makerspace_id, stream, audience, key, *args, **kwargs):
        makerspace = self._resolve_template(request, makerspace_id, stream, audience, key)
        payload = EmailTemplateUpdateSerializer(
            data=request.data,
            context={"stream": stream, "audience": audience, "key": key},
        )
        payload.is_valid(raise_exception=True)
        EmailTemplate.objects.update_or_create(
            makerspace=makerspace,
            stream=stream,
            audience=audience,
            key=key,
            defaults=payload.validated_data,
        )
        audit.record(
            request.user,
            "email_template.updated",
            makerspace=makerspace,
            target=makerspace,
            meta={"stream": stream, "audience": audience, "key": key},
        )
        return Response(
            EmailTemplateDetailSerializer(
                _detail_payload(makerspace, stream, audience, key)
            ).data,
        )


@extend_schema(tags=["Email templates"])
class EmailTemplateResetView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["post", "options"]

    @extend_schema(request=None, responses={200: EmailTemplateDetailSerializer})
    def post(self, request, makerspace_id, stream, audience, key, *args, **kwargs):
        if stream not in STREAM_ACTIONS or (stream, audience, key) not in REGISTRY:
            raise Http404
        makerspace = _resolve_makerspace(request.user, makerspace_id, stream)
        EmailTemplate.objects.filter(
            makerspace=makerspace,
            stream=stream,
            audience=audience,
            key=key,
        ).delete()
        audit.record(
            request.user,
            "email_template.reset",
            makerspace=makerspace,
            target=makerspace,
            meta={"stream": stream, "audience": audience, "key": key},
        )
        return Response(
            EmailTemplateDetailSerializer(
                _detail_payload(makerspace, stream, audience, key)
            ).data
        )


@extend_schema(tags=["Email templates"])
class EmailTemplatePreviewView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["post", "options"]

    @extend_schema(
        request=EmailTemplatePreviewRequestSerializer,
        responses={200: EmailTemplatePreviewResponseSerializer},
    )
    def post(self, request, makerspace_id, *args, **kwargs):
        payload = EmailTemplatePreviewRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        _resolve_makerspace(request.user, makerspace_id, data["stream"])
        return Response(
            render_preview(
                data["stream"],
                data["audience"],
                data["key"],
                data["subject"],
                data["text_body"],
                data["html_body"],
            )
        )
