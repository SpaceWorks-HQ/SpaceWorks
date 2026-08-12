"""OpenAPI and request serializers for notification recipient rules."""

from rest_framework import serializers

from apps.integrations.models_recipients import NotificationRecipientKind


class RecipientScopeSerializer(serializers.Serializer):
    machine_type_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )
    machine_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    category_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class RecipientRuleSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=NotificationRecipientKind.choices)
    role_id = serializers.IntegerField(required=False, allow_null=True)
    user_id = serializers.IntegerField(required=False, allow_null=True)
    scope = RecipientScopeSerializer(required=False)


class RecipientRulesPutSerializer(serializers.Serializer):
    feature = serializers.CharField(max_length=32)
    event = serializers.CharField(max_length=64)
    rules = RecipientRuleSerializer(many=True)


class RecipientRuleOutputSerializer(RecipientRuleSerializer):
    # Nullable because a delegated actor's payload can include a REDACTED PROJECTION of a
    # shared requester/members row -- their own scope links inside a row they do not own.
    # `project_special_row` withholds the real primary key there: PUT is not id-addressed,
    # so it confers nothing, and returning it would disclose a row belonging to someone
    # else. A generated client must therefore expect `id: null`, which is exactly what a
    # projection is: a rule with no addressable row of its own.
    id = serializers.IntegerField(allow_null=True)
    feature = serializers.CharField()
    event = serializers.CharField()


class RecipientFeatureSerializer(serializers.Serializer):
    key = serializers.CharField()
    events = serializers.ListField(child=serializers.CharField())


class RecipientRoleSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()


class RecipientMemberSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField(allow_blank=True)


class RecipientScopeOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class RecipientScopeOptionsSerializer(serializers.Serializer):
    machine_types = RecipientScopeOptionSerializer(many=True)
    machines = RecipientScopeOptionSerializer(many=True)
    categories = RecipientScopeOptionSerializer(many=True)


class ManagedPolicyMarkerSerializer(serializers.Serializer):
    feature = serializers.CharField()
    event = serializers.CharField()
    count = serializers.IntegerField(min_value=1)


class RecipientRulesResponseSerializer(serializers.Serializer):
    delegated = serializers.BooleanField()
    features = RecipientFeatureSerializer(many=True)
    roles = RecipientRoleSerializer(many=True)
    members = RecipientMemberSerializer(many=True)
    rules = RecipientRuleOutputSerializer(many=True)
    managed_policy_markers = ManagedPolicyMarkerSerializer(many=True)
    scope_options = RecipientScopeOptionsSerializer()
