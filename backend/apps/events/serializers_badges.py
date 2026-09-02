from rest_framework import serializers

from apps.events.badge_templates import MAX_BADGES


class BadgeTemplateSerializer(serializers.Serializer):
    version = serializers.IntegerField(required=False)
    paper_size = serializers.ChoiceField(
        choices=("A4", "LETTER", "custom"), required=False
    )
    orientation = serializers.ChoiceField(
        choices=("portrait", "landscape"), required=False
    )
    page_width_mm = serializers.FloatField(allow_null=True, required=False)
    page_height_mm = serializers.FloatField(allow_null=True, required=False)
    card_width_mm = serializers.FloatField(required=False)
    card_height_mm = serializers.FloatField(required=False)
    margin_mm = serializers.FloatField(required=False)
    gap_mm = serializers.FloatField(required=False)
    template = serializers.CharField(required=False)
    fields = serializers.ListField(
        child=serializers.CharField(max_length=80), required=False
    )
    font_size_pt = serializers.FloatField(required=False)
    name_font_size_pt = serializers.FloatField(required=False)
    text_align = serializers.ChoiceField(choices=("left", "center"), required=False)
    include_qr = serializers.BooleanField(required=False)


class BadgePdfRequestSerializer(serializers.Serializer):
    registration_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=MAX_BADGES,
    )
    template_override = BadgeTemplateSerializer(allow_null=True, required=False)
    include_attended = serializers.BooleanField(default=False, required=False)

