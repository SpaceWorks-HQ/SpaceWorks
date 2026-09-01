from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.data_export.models import DataExportJob

from .models_import_job import ImportIdentityDecision, TenantImportJob
from .models_protocol import DisclosureClosureApproval, MigrationPairing


class TypedErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
    code = serializers.CharField()


class FieldValidationErrorSerializer(serializers.Serializer):
    """DRF's field-keyed boundary errors; deliberately not the typed service shape."""

    non_field_errors = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    digest = serializers.ListField(child=serializers.CharField(), required=False)
    decisions = serializers.ListField(child=serializers.CharField(), required=False)
    approval_id = serializers.ListField(child=serializers.CharField(), required=False)
    target_age_recipient = serializers.ListField(child=serializers.CharField(), required=False)
    archive = serializers.ListField(child=serializers.CharField(), required=False)
    source_archive_digest = serializers.ListField(child=serializers.CharField(), required=False)
    target_identity = serializers.ListField(child=serializers.CharField(), required=False)
    receipt = serializers.ListField(child=serializers.CharField(), required=False)


class ClosureIdentitySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField(allow_blank=True)
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    display_name = serializers.CharField(allow_blank=True)
    phone = serializers.CharField(allow_blank=True)
    date_joined = serializers.DateTimeField()


class PendingClosureSerializer(serializers.Serializer):
    digest = serializers.CharField(max_length=64)
    identities = ClosureIdentitySerializer(many=True)


class IdentityDisclosureDecisionSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    approved = serializers.BooleanField()


class ClosureApprovalCreateSerializer(serializers.Serializer):
    digest = serializers.CharField(min_length=64, max_length=64)
    decisions = IdentityDisclosureDecisionSerializer(many=True)

    def validate_decisions(self, values):
        ids = [item["user_id"] for item in values]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Each closure identity may appear only once.")
        return values


class ClosureApprovalSerializer(serializers.ModelSerializer):
    identity_count = serializers.SerializerMethodField()
    approved_count = serializers.SerializerMethodField()

    class Meta:
        model = DisclosureClosureApproval
        fields = (
            "id", "closure_digest", "identity_count", "approved_count",
            "approved_at", "revoked_at",
        )

    def get_identity_count(self, obj):
        return len(obj.identity_ids)

    def get_approved_count(self, obj):
        return len(obj.approved_identity_ids)


class MigrationExportCreateSerializer(serializers.Serializer):
    approval_id = serializers.UUIDField()
    target_age_recipient = serializers.CharField(max_length=256, write_only=True)


class MigrationExportJobSerializer(serializers.ModelSerializer):
    source_retention_notice = serializers.SerializerMethodField()
    closure_digest = serializers.CharField(source="migration_export.closure_digest")
    format_version = serializers.IntegerField(source="migration_export.format_version")
    archive_digest = serializers.CharField(source="migration_export.archive_digest")

    class Meta:
        model = DataExportJob
        fields = (
            "id", "status", "failure_code", "failure_detail", "manifest",
            "closure_digest", "archive_digest", "format_version",
            "source_retention_notice",
            "created_at", "started_at", "completed_at", "expires_at",
        )

    def get_source_retention_notice(self, obj):
        return (
            "Migration does not delete the source tenant. Cutover archives it through "
            "the two-key receipt flow, and archives are outside the purge guarantee."
        )


class ImportCreateSerializer(serializers.Serializer):
    archive = serializers.FileField(write_only=True)
    source_archive_digest = serializers.RegexField(r"^[0-9a-f]{64}$")

    def validate_archive(self, value):
        if value.size <= 0:
            raise serializers.ValidationError("The encrypted archive is empty.")
        return value


class ImportJobSerializer(serializers.ModelSerializer):
    identity_count = serializers.SerializerMethodField()
    source_retention_notice = serializers.SerializerMethodField()
    target_lifecycle_state = serializers.SerializerMethodField()

    class Meta:
        model = TenantImportJob
        fields = (
            "id", "source_archive_digest", "source_makerspace_id",
            "source_makerspace_slug", "source_makerspace_name",
            "source_deployment_id", "storage_mode", "status", "identity_count",
            "target_lifecycle_state",
            "source_deployment_identity",
            "aggregate_outcome", "failure_code", "failure_detail", "created_at",
            "updated_at", "expires_at", "terminal_at", "scrubbed_at",
            "source_retention_notice",
        )

    def get_identity_count(self, obj):
        return obj.identity_decisions.count()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_target_lifecycle_state(self, obj):
        target = obj.target_makerspace
        return target.lifecycle_state if target is not None else None

    def get_source_retention_notice(self, obj):
        return (
            "Migration does not delete the source tenant. Cutover archives it, and "
            "archives are outside the purge guarantee."
        )


class ImportIdentityDecisionSerializer(serializers.Serializer):
    source_user_id = serializers.CharField(max_length=255)
    identity_resolution = serializers.ChoiceField(
        choices=ImportIdentityDecision.IdentityResolution.choices
    )
    membership_disposition = serializers.ChoiceField(
        choices=ImportIdentityDecision.MembershipDisposition.choices
    )
    target_user_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        target = attrs.get("target_user_id")
        linked = attrs["identity_resolution"] == "link_existing"
        if linked != (target is not None):
            raise serializers.ValidationError(
                {"target_user_id": "Required only for link_existing decisions."}
            )
        return attrs


class ImportDecisionListSerializer(serializers.Serializer):
    decisions = ImportIdentityDecisionSerializer(many=True)

    def validate_decisions(self, values):
        source_ids = [item["source_user_id"] for item in values]
        targets = [item["target_user_id"] for item in values if item.get("target_user_id")]
        if len(source_ids) != len(set(source_ids)):
            raise serializers.ValidationError("Each source identity may appear only once.")
        if len(targets) != len(set(targets)):
            raise serializers.ValidationError("A target account may be linked only once.")
        from apps.accounts.models import User

        existing = set(User.objects.filter(pk__in=targets).values_list("pk", flat=True))
        if existing != set(targets):
            raise serializers.ValidationError("A linked target account does not exist.")
        return values


class ImportRunSerializer(serializers.Serializer):
    target_identity = serializers.DictField(required=False, default=dict)

    def validate_target_identity(self, value):
        if set(value) - {"name", "slug"}:
            raise serializers.ValidationError("Only name and slug may be overridden.")
        return value


class VerificationReportSerializer(serializers.Serializer):
    format_version = serializers.IntegerField()
    target_makerspace_id = serializers.IntegerField()
    imported = serializers.DictField()
    resolved = serializers.DictField()
    dropped = serializers.DictField()
    identities_linked = serializers.IntegerField()
    identities_created = serializers.IntegerField()
    external_references_created = serializers.IntegerField()


class PairingCreateSerializer(serializers.Serializer):
    migration_id = serializers.UUIDField()
    source_tenant_id = serializers.CharField(max_length=64)
    archive_digest = serializers.RegexField(r"^[0-9a-f]{64}$")
    source = serializers.DictField()
    target = serializers.DictField()


class ReceiptEnvelopeSerializer(serializers.Serializer):
    payload = serializers.DictField()
    signer_fingerprint = serializers.CharField(max_length=64)
    signature = serializers.CharField(max_length=88)


class CutoverReceiptRequestSerializer(serializers.Serializer):
    receipt = ReceiptEnvelopeSerializer()


class PairingSerializer(serializers.ModelSerializer):
    class Meta:
        model = MigrationPairing
        fields = (
            "id", "migration_id", "source_tenant_id", "archive_digest",
            "source_deployment_id", "source_fingerprint", "target_deployment_id",
            "target_fingerprint", "approved_at",
        )


class CutoverOutcomeSerializer(serializers.Serializer):
    message = serializers.CharField()
    receipt = ReceiptEnvelopeSerializer(required=False)


class DeploymentIdentitySerializer(serializers.Serializer):
    algorithm = serializers.CharField()
    deployment_id = serializers.CharField()
    public_key = serializers.CharField()
    fingerprint = serializers.CharField()
    age_recipient = serializers.CharField()
