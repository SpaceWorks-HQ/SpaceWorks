from rest_framework import serializers


class UsageResourceSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    used = serializers.IntegerField(allow_null=True)
    limit = serializers.IntegerField(allow_null=True)
    unit = serializers.ChoiceField(choices=("bytes", "count"))


class MakerspaceUsageSerializer(serializers.Serializer):
    makerspace_id = serializers.IntegerField()
    managed = serializers.BooleanField()
    resources = UsageResourceSerializer(many=True)


class PlatformTenantUsageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    usage = MakerspaceUsageSerializer()


class PlatformBackupHealthSerializer(serializers.Serializer):
    automatic_enabled = serializers.BooleanField()
    last_success_at = serializers.DateTimeField(allow_null=True)
    status = serializers.CharField()
    started_at = serializers.DateTimeField(allow_null=True)
    finished_at = serializers.DateTimeField(allow_null=True)
    has_error = serializers.BooleanField()
    cadence_minutes = serializers.IntegerField()


class PlatformOffsiteHealthSerializer(serializers.Serializer):
    name = serializers.CharField()
    state = serializers.CharField()
    verified_at = serializers.DateTimeField(allow_null=True)
    has_error = serializers.BooleanField()


class PlatformTaskHealthSerializer(serializers.Serializer):
    name = serializers.CharField()
    task = serializers.CharField()
    cadence_minutes = serializers.IntegerField()
    last_run_at = serializers.DateTimeField(allow_null=True)
    status = serializers.ChoiceField(choices=("ok", "warn", "error"))


class FailedDeliveriesSerializer(serializers.Serializer):
    email = serializers.IntegerField()
    notifications = serializers.IntegerField()


class PlatformDashboardSerializer(serializers.Serializer):
    checked_at = serializers.DateTimeField()
    tenants_by_state = serializers.DictField(child=serializers.IntegerField())
    usage_totals = serializers.DictField(child=serializers.IntegerField())
    tenants = PlatformTenantUsageSerializer(many=True)
    backup = PlatformBackupHealthSerializer()
    offsite = PlatformOffsiteHealthSerializer(many=True)
    scheduler = PlatformTaskHealthSerializer(many=True)
    failed_deliveries = FailedDeliveriesSerializer()


class PlatformProblemSerializer(serializers.Serializer):
    key = serializers.CharField()
    status = serializers.ChoiceField(choices=("ok", "warn", "error"))
    message = serializers.CharField()
    fix_url = serializers.CharField()
    makerspace_id = serializers.IntegerField(allow_null=True)


class PlatformProblemsSerializer(serializers.Serializer):
    checked_at = serializers.DateTimeField()
    status = serializers.ChoiceField(choices=("ok", "warn", "error"))
    results = PlatformProblemSerializer(many=True)
