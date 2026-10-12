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

    def _feature_flags(self, obj):
        from apps.makerspaces.platform import feature_enabled, module_enabled
        # The list query already proves host servability. Resolve live capability
        # checks once per host, rather than querying restoration state per field/row.
        cache = self.context.setdefault("ticket_feature_flags", {})
        if obj.makerspace_id not in cache:
            cache[obj.makerspace_id] = {
                "tickets": feature_enabled(obj.makerspace, "events.ticket_types"),
                "promos": feature_enabled(obj.makerspace, "events.promo_codes"),
                "membership": module_enabled(obj.makerspace, "membership"),
            }
        return cache[obj.makerspace_id]

    @extend_schema_field(serializers.BooleanField())
    def get_ticket_selection_required(self, obj):
        from .ticketing import ticket_selection_required
        if hasattr(obj, "public_ticket_rows"):
            return self._feature_flags(obj)["tickets"] and any(
                row.makerspace_id == obj.makerspace_id for row in obj.public_ticket_rows
            )
        return ticket_selection_required(obj)

    @extend_schema_field({"type": "object", "nullable": True, "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "slug": {"type": "string"}}})
    def get_category(self, obj):
        return {"id": obj.category_id, "name": obj.category.name, "slug": obj.category.slug} if obj.category_id else None

    @extend_schema_field({"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "amount": {"type": "string"}, "audience": {"type": "string"}, "spots_left": {"type": "integer", "nullable": True}}}})
    def get_ticket_types(self, obj):
        from .ticketing import available_ticket_types
        from .capacity import registration_spots_left
        request = self.context.get("request")
        if hasattr(obj, "public_ticket_rows"):
            from django.utils import timezone
            flags = self._feature_flags(obj)
            if not flags["tickets"]:
                return []
            now = timezone.now()
            member = flags["membership"] and obj.makerspace_id in self.context.get("ticket_membership_ids", set())
            rows = [row for row in obj.public_ticket_rows if
                    row.makerspace_id == obj.makerspace_id
                    and (row.sales_start_at is None or row.sales_start_at <= now)
                    and (row.sales_end_at is None or row.sales_end_at > now)
                    and (member or row.audience == "public")]
        else:
            rows = available_ticket_types(obj, getattr(request, "user", None))
        return [{"id": row.pk, "name": row.name, "amount": str(row.amount), "audience": row.audience, "spots_left": registration_spots_left(obj, row)} for row in rows]

    @extend_schema_field(serializers.BooleanField())
    def get_promo_codes_enabled(self, obj):
        return self._feature_flags(obj)["promos"]
