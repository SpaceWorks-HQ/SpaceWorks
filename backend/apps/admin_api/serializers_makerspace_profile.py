from zoneinfo import available_timezones

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.makerspaces.opening_hours_schema import OpeningHoursField
from apps.makerspaces.profile_validation import (
    COUNTRY_CODES, validate_country, validate_opening_hours, validate_timezone,
)
from apps.payments.models import currency_validator


class MakerspaceProfileSerializer(serializers.Serializer):
    timezone = serializers.CharField(max_length=100, validators=[validate_timezone])
    country = serializers.CharField(max_length=2, allow_blank=True, validators=[validate_country])
    opening_hours = OpeningHoursField(validators=[validate_opening_hours])
    default_currency = serializers.CharField(max_length=3)
    timezone_choices = serializers.ListField(child=serializers.CharField(), read_only=True)
    country_choices = serializers.ListField(child=serializers.CharField(), read_only=True)

    def validate_default_currency(self, value):
        value = value.lower()
        try:
            currency_validator(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value

    def validate(self, attrs):
        unknown = set(self.initial_data) - {"timezone", "country", "opening_hours", "default_currency"}
        if unknown:
            raise serializers.ValidationError({name: ["Unknown profile field."] for name in sorted(unknown)})
        return attrs


class ProfileErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField()
    fields = serializers.DictField(child=serializers.ListField(child=serializers.CharField()))


class ProfileGateErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField()
    purpose = serializers.CharField(required=False)


def profile_payload(makerspace, payment_settings):
    return {
        "timezone": makerspace.timezone,
        "country": makerspace.country,
        "opening_hours": makerspace.opening_hours,
        "default_currency": payment_settings.default_currency,
        "timezone_choices": sorted(available_timezones()),
        "country_choices": COUNTRY_CODES,
    }
