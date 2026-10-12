from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.accounts.models import User
from apps.admin_api.serializers_users import UserSerializer
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.admin_api.serializers_payment_summary import PaymentSummaryMixin


class MembershipRoleSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = MakerspaceRole
        fields = ("id", "name", "slug", "legacy_role", "is_default", "is_protected")
        read_only_fields = fields


class MembershipListSerializer(PaymentSummaryMixin, serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    payment = serializers.SerializerMethodField()
    makerspace_id = serializers.IntegerField(source="makerspace.id", read_only=True)
    makerspace_slug = serializers.SlugField(source="makerspace.slug", read_only=True)
    assigned_role = MembershipRoleSummarySerializer(allow_null=True, read_only=True)

    class Meta:
        model = MakerspaceMembership
        fields = (
            "id", "user", "makerspace_id", "makerspace_slug", "role",
            "assigned_role", "status", "created_at", "payment",
        )
        read_only_fields = fields


class MembershipCreateSerializer(serializers.Serializer):
    # Bound the account fields to the User column limits so an oversized value is a
    # clean 400 at the boundary instead of a PostgreSQL DataError -> 500 when a NEW
    # account is inserted (P2).
    username = serializers.CharField(max_length=User._meta.get_field("username").max_length)
    email = serializers.EmailField(
        required=False, allow_blank=True, max_length=User._meta.get_field("email").max_length
    )
    first_name = serializers.CharField(
        required=False, allow_blank=True, max_length=User._meta.get_field("first_name").max_length
    )
    last_name = serializers.CharField(
        required=False, allow_blank=True, max_length=User._meta.get_field("last_name").max_length
    )
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    role_id = serializers.IntegerField()

    def validate_password(self, value):
        if not value:
            return value
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


class MembershipRoleAssignSerializer(serializers.Serializer):
    role_id = serializers.IntegerField()
