"""Admission boundary and read schemas shared by staff and applicant routes."""
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.forms_schema.serializers import CustomFormSchemaField
from apps.makerspaces.membership_admission_forms import answers_for
from apps.makerspaces.membership_admission_settings import RECIPES
from apps.makerspaces.models import MakerspaceMembershipSettings, MembershipPlan, MembershipRequest, MembershipVouch


class AdmissionSettingsSerializer(serializers.ModelSerializer):
    recipe = serializers.ChoiceField(choices=tuple(RECIPES), required=False, write_only=True)
    application_schema = CustomFormSchemaField(required=False, allow_null=True)
    default_plan = serializers.PrimaryKeyRelatedField(queryset=MembershipPlan.objects.none(), required=False, allow_null=True)
    vouches_required = serializers.IntegerField(min_value=1, max_value=5, required=False)
    voucher_pending_limit = serializers.IntegerField(min_value=1, max_value=100, required=False)
    voucher_min_tenure_days = serializers.IntegerField(min_value=0, max_value=3650, required=False)
    vouch_expiry_days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    request_expiry_days = serializers.IntegerField(min_value=1, max_value=365, required=False)
    joining_fee_currency = serializers.RegexField(r"^[A-Za-z]{3}$", required=False)

    class Meta:
        model = MakerspaceMembershipSettings
        fields = ("configured", "join_mode", "vouches_required", "voucher_min_tenure_days", "voucher_pending_limit",
                  "vouch_expiry_days", "vouch_replaces_approval", "payment_timing", "application_schema",
                  "default_plan", "joining_fee", "joining_fee_currency", "rejoin_dues_rule", "request_expiry_days", "recipe")
        read_only_fields = ("configured",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        space = self.context.get("makerspace")
        if space:
            self.fields["default_plan"].queryset = MembershipPlan.objects.filter(makerspace=space, is_active=True)

    def validate_joining_fee_currency(self, value):
        return value.lower()


class PublicAdmissionSerializer(serializers.Serializer):
    join_mode = serializers.CharField()
    vouches_required = serializers.IntegerField()
    application_schema = serializers.JSONField(allow_null=True)
    default_plan = serializers.DictField(allow_null=True)
    joining_fee = serializers.DecimalField(max_digits=12, decimal_places=2)
    joining_fee_currency = serializers.CharField()
    payment_timing = serializers.CharField()


class VouchSerializer(serializers.ModelSerializer):
    voucher_id = serializers.IntegerField()
    voucher_name = serializers.CharField(source="voucher.display_name")

    class Meta:
        model = MembershipVouch
        fields = ("voucher_id", "voucher_name", "created_at", "expires_at")


class AdmissionPaymentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField()


class AdmissionRequestSerializer(serializers.ModelSerializer):
    application_answers = serializers.SerializerMethodField()
    vouches = VouchSerializer(many=True)
    admission_payment = AdmissionPaymentSerializer(allow_null=True)

    class Meta:
        model = MembershipRequest
        fields = ("id", "state", "application_answers", "vouches", "admission_payment", "expires_at")

    @extend_schema_field(serializers.JSONField(allow_null=True))
    def get_application_answers(self, obj):
        return answers_for(obj)


class AdmissionExportSerializer(serializers.Serializer):
    requests = AdmissionRequestSerializer(many=True)


class AdmissionVouchOutcomeSerializer(serializers.ModelSerializer):
    """A voucher receives the outcome, never the applicant's private submission."""
    class Meta:
        model = MembershipRequest
        fields = ("id", "state")


class AdmissionAnswersSerializer(serializers.Serializer):
    application_answers = serializers.JSONField(required=False, allow_null=True)
