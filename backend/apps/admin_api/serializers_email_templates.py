"""Serializers for the email-template surfaces.

A neutral leaf: it imports the registry validator and nothing from the view modules, so
both `views_email_templates_space` and `views_email_templates_types` can depend on it
without the submodules ever depending on each other -- the barrel-split cycle that bit
`procurement/views_items_export.py`. Extracted from `views_email_templates_common.py` to
keep that module under the ~300-line ceiling.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.integrations.email_templates_registry import validate_email_template_strings


class MachineTypeOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_overridden = serializers.BooleanField(read_only=True)


class EmailTemplateDetailSerializer(serializers.Serializer):
    stream = serializers.CharField(read_only=True)
    audience = serializers.CharField(read_only=True)
    key = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    fields = serializers.ListField(child=serializers.DictField(), read_only=True)
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
    can_edit_space_default = serializers.BooleanField(read_only=True)
    overridable_types = MachineTypeOptionSerializer(many=True, read_only=True)


class EmailTemplateUpdateSerializer(serializers.Serializer):
    subject = serializers.CharField(allow_blank=True, max_length=200)
    text_body = serializers.CharField(allow_blank=True)
    html_body = serializers.CharField(allow_blank=True)
    is_active = serializers.BooleanField()

    def validate(self, attrs):
        try:
            validate_email_template_strings(
                self.context["stream"], self.context["audience"], self.context["key"],
                attrs["subject"], attrs["text_body"], attrs["html_body"],
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return attrs


class EmailTemplatePreviewRequestSerializer(serializers.Serializer):
    stream = serializers.CharField()
    audience = serializers.CharField()
    key = serializers.CharField()
    machine_type_id = serializers.IntegerField(required=False)
    subject = serializers.CharField(allow_blank=True, max_length=200)
    text_body = serializers.CharField(allow_blank=True)
    html_body = serializers.CharField(allow_blank=True)

    def validate(self, attrs):
        try:
            validate_email_template_strings(
                attrs["stream"], attrs["audience"], attrs["key"], attrs["subject"],
                attrs["text_body"], attrs["html_body"],
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return attrs


class EmailTemplatePreviewResponseSerializer(serializers.Serializer):
    subject = serializers.CharField(read_only=True)
    text_body = serializers.CharField(read_only=True)
    html_body = serializers.CharField(read_only=True)
