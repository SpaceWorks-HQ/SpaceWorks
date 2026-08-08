from rest_framework import serializers

from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import available_modules


class MakerspaceSwitcherSerializer(serializers.ModelSerializer):
    """Minimal makerspace row for the staff console switcher."""

    enabled_modules = serializers.SerializerMethodField()

    def get_enabled_modules(self, obj) -> list[str]:
        # The console turns these keys straight into tabs, so it must be told what
        # this deployment actually serves. A tombstoned app's key stays stored on the
        # row -- uninstall retains data -- but shipping it here would render a tab
        # whose every request 404s.
        return available_modules(obj)

    class Meta:
        model = Makerspace
        fields = [
            "id",
            "name",
            "public_code",
            "slug",
            "telegram_group_chat_id",
            # Module flags are frontend-safe (already in the public bootstrap) and are
            # required so the console can gate module tabs (Machines, Events, ...) for a
            # switcher-slim role such as machine_manager / print_manager.
            "enabled_modules",
            "enabled_features",
        ]
        read_only_fields = fields


class MakerspaceDisabledRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = Makerspace
        fields = [
            "id",
            "name",
            "slug",
            "public_code",
            "location",
            "superadmin_access_enabled",
        ]
        read_only_fields = fields


class ReturnPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = Makerspace
        fields = ["id", "default_loan_days"]
        read_only_fields = ["id"]

    def validate_default_loan_days(self, value):
        if value < 1:
            raise serializers.ValidationError("Default loan days must be at least 1.")
        return value