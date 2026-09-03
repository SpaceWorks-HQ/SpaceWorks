from rest_framework import serializers

from apps.makerspaces.member_card_services import REISSUE_REASONS
from apps.makerspaces.models import MemberCard


class MemberCardSerializer(serializers.ModelSerializer):
    """Never carries the photo key or a URL that outlives the response."""

    membership_id = serializers.IntegerField(read_only=True, allow_null=True)
    is_active = serializers.BooleanField(read_only=True)
    photo_set = serializers.SerializerMethodField()
    qr_active = serializers.SerializerMethodField()

    class Meta:
        model = MemberCard
        fields = (
            "id", "card_number", "printed_name", "membership_id", "is_active", "photo_set",
            "photo_consent_at", "qr_active", "print_count", "last_printed_at", "issued_at",
            "revoked_at", "revoked_reason", "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_photo_set(self, obj) -> bool:
        return bool(obj.photo_object_key)

    def get_qr_active(self, obj) -> bool:
        return getattr(obj, "_qr_active", None) is not False and obj.is_active


class MemberCardIssueSerializer(serializers.Serializer):
    printed_name = serializers.CharField(max_length=200, required=False, allow_blank=True)


class MemberCardReissueSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=[(r, r) for r in REISSUE_REASONS])


class MemberCardRevokeSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=32, required=False, allow_blank=True)


class MemberCardOwnUpdateSerializer(serializers.Serializer):
    printed_name = serializers.CharField(max_length=200, allow_blank=True)


class MemberCardPhotoPresignSerializer(serializers.Serializer):
    content_type = serializers.CharField(max_length=64)


class MemberCardPhotoFinalizeSerializer(serializers.Serializer):
    object_key = serializers.CharField(max_length=300)
    content_type = serializers.CharField(max_length=64)
    consent = serializers.BooleanField()


class MemberCardPrintSerializer(serializers.Serializer):
    card_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)
    preset = serializers.ChoiceField(choices=[("sheet", "sheet"), ("single", "single")], required=False, default="sheet")


class MemberCardResolveSerializer(serializers.Serializer):
    payload = serializers.CharField(max_length=64)


class MemberCardResolveResultSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=[("ok", "ok"), ("revoked", "revoked"), ("inactive", "inactive")])
    card_id = serializers.IntegerField(required=False)
    card_number = serializers.IntegerField(required=False)
    printed_name = serializers.CharField(required=False, allow_blank=True)
    membership_id = serializers.IntegerField(required=False)
    membership_status = serializers.CharField(required=False)
    photo_url = serializers.CharField(required=False, allow_null=True)


class MemberCardTemplateSerializer(serializers.Serializer):
    version = serializers.IntegerField(required=False)
    page = serializers.CharField(required=False)
    orientation = serializers.CharField(required=False)
    card_width_mm = serializers.FloatField(required=False)
    card_height_mm = serializers.FloatField(required=False)
    margin_mm = serializers.FloatField(required=False)
    gap_mm = serializers.FloatField(required=False)
    front_fields = serializers.ListField(child=serializers.CharField(), required=False)
    back_text = serializers.CharField(required=False, allow_blank=True)
    include_photo = serializers.BooleanField(required=False)
    include_qr = serializers.BooleanField(required=False)
    name_font_size_pt = serializers.IntegerField(required=False)
    font_size_pt = serializers.IntegerField(required=False)
    crop_marks = serializers.BooleanField(required=False)
