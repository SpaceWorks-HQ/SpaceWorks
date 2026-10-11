from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from apps.events.models import Event


class EventTicketingPublicSerializer(serializers.Serializer):
    registration_audience = serializers.ChoiceField(choices=Event.RegistrationAudience.choices, read_only=True)
    category = serializers.SerializerMethodField()
    tags = serializers.ListField(child=serializers.CharField(), read_only=True)
    ticket_types = serializers.SerializerMethodField()
    promo_codes_enabled = serializers.SerializerMethodField()
    ticket_selection_required = serializers.SerializerMethodField()

    @extend_schema_field(serializers.BooleanField())
    def get_ticket_selection_required(self, obj):
        from .ticketing import ticket_selection_required
        return ticket_selection_required(obj)

    @extend_schema_field({"type": "object", "nullable": True, "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "slug": {"type": "string"}}})
    def get_category(self, obj):
        return {"id": obj.category_id, "name": obj.category.name, "slug": obj.category.slug} if obj.category_id else None

    @extend_schema_field({"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "amount": {"type": "string"}, "audience": {"type": "string"}, "spots_left": {"type": "integer", "nullable": True}}}})
    def get_ticket_types(self, obj):
        from .ticketing import available_ticket_types
        from .capacity import registration_spots_left
        request = self.context.get("request")
        return [{"id": row.pk, "name": row.name, "amount": str(row.amount), "audience": row.audience, "spots_left": registration_spots_left(obj, row)} for row in available_ticket_types(obj, getattr(request, "user", None))]

    @extend_schema_field(serializers.BooleanField())
    def get_promo_codes_enabled(self, obj):
        from apps.makerspaces.platform import feature_enabled
        return feature_enabled(obj.makerspace, "events.promo_codes")

