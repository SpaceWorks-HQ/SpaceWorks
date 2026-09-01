from django.db.models import Count
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.makerspaces.models import MakerspaceRole


class RoleSerializer(serializers.ModelSerializer):
    makerspace_id = serializers.IntegerField(read_only=True)
    granted_actions = serializers.SerializerMethodField()
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = MakerspaceRole
        fields = (
            "id", "makerspace_id", "name", "slug", "granted_actions", "legacy_role",
            "is_default", "is_protected", "member_count", "created_at", "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_granted_actions(self, obj):
        return sorted(obj.granted_actions) if isinstance(obj.granted_actions, list) else []


class RoleWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, trim_whitespace=True, required=False)
    granted_actions = serializers.ListField(child=serializers.CharField(), required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("At least one field is required.")
        if "name" in attrs and not attrs["name"]:
            raise serializers.ValidationError({"name": "This field may not be blank."})
        return attrs


class RoleCreateSerializer(RoleWriteSerializer):
    name = serializers.CharField(max_length=80, trim_whitespace=True)
    granted_actions = serializers.ListField(child=serializers.CharField())


class MachineScopeOptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    label = serializers.CharField()
    # Global built-in types are selectable by every makerspace, so the console has to be
    # able to say which ones are shared rather than this lab's own.
    is_builtin = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)


class RoleMachineScopeSerializer(serializers.Serializer):
    """The role's links plus everything it could be linked to, in one round trip."""

    machine_type_ids = serializers.ListField(child=serializers.IntegerField())
    machine_ids = serializers.ListField(child=serializers.IntegerField())
    available_machine_types = MachineScopeOptionSerializer(many=True, read_only=True)
    available_machines = MachineScopeOptionSerializer(many=True, read_only=True)
    # False when the role holds MANAGE_MAKERSPACE (or is otherwise exempt): the console
    # must render the editor as inert rather than let an administrator tick boxes that
    # `role_scope` will ignore.
    scoping_applies = serializers.BooleanField(read_only=True)


class RoleMachineScopeWriteSerializer(serializers.Serializer):
    machine_type_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=True
    )
    machine_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=True
    )


class CapabilitySerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField()
    group = serializers.CharField()
    grantable = serializers.BooleanField()
    lock_reason = serializers.CharField(allow_null=True)


def role_queryset():
    return MakerspaceRole.objects.annotate(member_count=Count("memberships"))
