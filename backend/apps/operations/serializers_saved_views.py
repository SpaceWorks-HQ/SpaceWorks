from rest_framework import serializers

from apps.admin_api.staff_list_scope import ENTITY_ACTIONS
from apps.operations.models_saved_views import SavedView


class SavedViewSerializer(serializers.ModelSerializer):
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    entity = serializers.ChoiceField(choices=list(ENTITY_ACTIONS))
    state = serializers.DictField(child=serializers.CharField(max_length=250, allow_blank=True))

    class Meta:
        model = SavedView
        fields = ["id", "makerspace", "owner", "owner_username", "name", "entity", "state", "shared", "created_at", "updated_at"]
        read_only_fields = ["id", "makerspace", "owner", "created_at", "updated_at"]

    def validate_state(self, value):
        if len(value) > 20:
            raise serializers.ValidationError("At most 20 list-state keys are allowed.")
        # Values are filter snapshots, never navigation URLs or executable actions.
        allowed = {"id", "q", "search", "ordering", "page", "status", "subject_type", "due_state", "archived", "low_stock", "role", "state", "starts_at", "ends_at", "action", "actor", "targetType", "targetId", "start", "end", "history", "pendingPage", "acceptedPage", "activePage", "historyPage", "requestPage", "requestState", "requestOrdering"}
        if set(value) - allowed:
            raise serializers.ValidationError("Unsupported list-state key.")
        return value


class SavedViewListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = SavedViewSerializer(many=True)
