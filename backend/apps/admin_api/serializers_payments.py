from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.payments.credential_validation import (
    RAW_CREDENTIAL_FIELDS,
    update_payment_settings,
    update_platform_payment_settings,
    validate_raw_credential_changes,
)
from apps.payments.models import (
    MakerspacePaymentSettings,
    PlatformStripeConnectSettings,
    currency_validator,
)
from apps.payments.resolution import resolve_payment_source


class MakerspacePaymentSettingsSerializer(serializers.ModelSerializer):
    default_currency = serializers.CharField(required=False, max_length=3)
    stripe_publishable_key = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=255
    )
    stripe_secret_key = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    stripe_webhook_secret = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    stripe_secret_key_set = serializers.SerializerMethodField()
    stripe_webhook_secret_set = serializers.SerializerMethodField()
    stripe_publishable_key_set = serializers.SerializerMethodField()
    effective_mode = serializers.SerializerMethodField()

    class Meta:
        model = MakerspacePaymentSettings
        fields = (
            "default_currency",
            "stripe_publishable_key",
            "stripe_publishable_key_set",
            "stripe_secret_key",
            "stripe_secret_key_set",
            "stripe_webhook_secret",
            "stripe_webhook_secret_set",
            "connect_account_id",
            "connect_status",
            "connect_charges_enabled",
            "connect_payouts_enabled",
            "connect_status_updated_at",
            "effective_mode",
            "loan_deposit_mode",
            "loan_deposit_amount",
            "loan_late_fee_per_day",
            "loan_late_fee_cap",
            "loan_grace_days",
            "loan_deposit_blocks_issue",
        )
        read_only_fields = (
            "connect_account_id",
            "connect_status",
            "connect_charges_enabled",
            "connect_payouts_enabled",
            "connect_status_updated_at",
            "effective_mode",
        )

    def get_stripe_secret_key_set(self, obj) -> bool:
        return obj.stripe_secret_key_set

    def get_stripe_publishable_key_set(self, obj) -> bool:
        return obj.stripe_publishable_key_set

    def get_stripe_webhook_secret_set(self, obj) -> bool:
        return obj.stripe_webhook_secret_set

    def get_effective_mode(self, obj) -> str:
        source = resolve_payment_source(obj.makerspace)
        return source.provider if source else "unavailable"

    def validate_default_currency(self, value):
        normalized = value.strip().lower()
        try:
            currency_validator(normalized)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return normalized

    def validate(self, attrs):
        credential_changes = {
            field: attrs[field] for field in RAW_CREDENTIAL_FIELDS if field in attrs
        }
        try:
            validate_raw_credential_changes(self.instance, credential_changes)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        return attrs

    def update(self, instance, validated_data):
        try:
            return update_payment_settings(instance, validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc


class PaymentSettingsErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()


class StripeConnectOnboardingSerializer(serializers.Serializer):
    authorize_url = serializers.URLField()


class PlatformStripeConnectSettingsSerializer(serializers.ModelSerializer):
    stripe_publishable_key = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=255
    )
    stripe_secret_key = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    stripe_webhook_secret = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    stripe_secret_key_set = serializers.SerializerMethodField()
    stripe_webhook_secret_set = serializers.SerializerMethodField()
    stripe_publishable_key_set = serializers.SerializerMethodField()

    class Meta:
        model = PlatformStripeConnectSettings
        fields = (
            "id",
            "stripe_publishable_key",
            "stripe_publishable_key_set",
            "stripe_secret_key",
            "stripe_secret_key_set",
            "stripe_webhook_secret",
            "stripe_webhook_secret_set",
            "stripe_connect_client_id",
            "application_fee_bps",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "stripe_publishable_key_set",
            "stripe_secret_key_set",
            "stripe_webhook_secret_set",
            "updated_at",
        )

    def get_stripe_secret_key_set(self, obj) -> bool:
        return bool(obj.stripe_secret_key)

    def get_stripe_publishable_key_set(self, obj) -> bool:
        return obj.stripe_publishable_key_set

    def get_stripe_webhook_secret_set(self, obj) -> bool:
        return bool(obj.stripe_webhook_secret)

    def update(self, instance, validated_data):
        try:
            return update_platform_payment_settings(instance, validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
