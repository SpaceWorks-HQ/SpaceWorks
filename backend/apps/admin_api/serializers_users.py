from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "access_status",
            "restriction_reason",
            "telegram_user_id",
            "external_checkin_user_id",
            "is_active",
        ]
        read_only_fields = ["id"]


class StaffMembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer()
    makerspace_id = serializers.IntegerField(source="makerspace.id")
    makerspace_slug = serializers.SlugField(source="makerspace.slug")

    class Meta:
        model = MakerspaceMembership
        fields = ["id", "user", "makerspace_id", "makerspace_slug", "role", "created_at"]


class StaffCreateSerializer(serializers.Serializer):
    username = serializers.CharField()
    email = serializers.EmailField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    makerspace_id = serializers.IntegerField()
    # GUEST_ADMIN is absent: it is no longer a built-in role (migration 0052), so there is
    # no seeded role for this legacy fixed-role surface to attach a user to.
    role = serializers.ChoiceField(
        choices=[
            MakerspaceMembership.Role.SPACE_MANAGER,
            MakerspaceMembership.Role.INVENTORY_MANAGER,
            MakerspaceMembership.Role.PRINT_MANAGER,
            MakerspaceMembership.Role.MACHINE_MANAGER,
        ]
    )
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    def validate_password(self, value):
        if not value:
            return value
        # Build an unsaved User from the submitted fields so
        # UserAttributeSimilarityValidator (enabled in settings) can reject a
        # password derived from the username/email/name. Without user context that
        # validator is silently skipped.
        candidate_user = User(
            username=self.initial_data.get("username", "") or "",
            email=self.initial_data.get("email", "") or "",
            first_name=self.initial_data.get("first_name", "") or "",
            last_name=self.initial_data.get("last_name", "") or "",
        )
        try:
            validate_password(value, user=candidate_user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return value


class RestrictUserSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=False, trim_whitespace=True)
    status = serializers.ChoiceField(
        choices=[User.AccessStatus.RESTRICTED, User.AccessStatus.SUSPENDED],
        default=User.AccessStatus.RESTRICTED,
    )


class ResetPasswordRequestSerializer(serializers.Serializer):
    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=False,
        min_length=8,
    )


class ResetPasswordResponseSerializer(serializers.Serializer):
    username = serializers.CharField()
    temporary_password = serializers.CharField()


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor",
            "action",
            "makerspace",
            "target_type",
            "target_id",
            "meta",
            "created_at",
        ]
