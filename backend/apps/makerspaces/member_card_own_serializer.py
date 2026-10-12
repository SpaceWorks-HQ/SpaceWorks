"""The active member may save their own QR; staff list projections stay unchanged."""
import segno
from rest_framework import serializers

from .member_card_serializers import MemberCardSerializer
from .member_card_services import active_qr


class OwnMemberCardSerializer(MemberCardSerializer):
    qr_image = serializers.SerializerMethodField()

    class Meta(MemberCardSerializer.Meta):
        fields = MemberCardSerializer.Meta.fields + ("qr_image",)
        read_only_fields = fields

    def get_qr_image(self, card) -> str | None:
        qr = active_qr(card) if card.is_active else None
        return segno.make(qr.payload).png_data_uri(scale=6) if qr else None

    def get_qr_active(self, card) -> bool:
        return bool(card.is_active and active_qr(card))
