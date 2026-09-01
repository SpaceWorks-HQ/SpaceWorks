from rest_framework import serializers

from apps.integrations.smtp_validation import validate_smtp_settings
from apps.integrations.webhook_validation import validate_webhook_url
from apps.makerspaces.models import Makerspace


class ApiIntegrationSettingsSerializer(serializers.ModelSerializer):
    public_api_key = serializers.CharField(read_only=True)
    cors_allowed_origins = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    telegram_bot_token = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    smtp_password = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    telegram_bot_token_set = serializers.SerializerMethodField()
    smtp_password_set = serializers.SerializerMethodField()
    slack_webhook_url = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=2048
    )
    mattermost_webhook_url = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=2048
    )
    discord_webhook_url = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=2048
    )
    slack_webhook_url_set = serializers.SerializerMethodField()
    mattermost_webhook_url_set = serializers.SerializerMethodField()
    discord_webhook_url_set = serializers.SerializerMethodField()

    class Meta:
        model = Makerspace
        fields = [
            "public_code", "public_api_key", "cors_allowed_origins",
            "telegram_group_chat_id", "telegram_bot_token",
            "telegram_bot_token_set", "smtp_host", "smtp_port", "smtp_username",
            "smtp_password", "smtp_password_set", "smtp_use_tls", "smtp_use_ssl",
            "smtp_from_email", "slack_webhook_url", "slack_webhook_url_set",
            "mattermost_webhook_url", "mattermost_webhook_url_set",
            "discord_webhook_url", "discord_webhook_url_set", "default_loan_days",
        ]
        read_only_fields = [
            "public_code", "public_api_key", "cors_allowed_origins",
            "telegram_bot_token_set", "smtp_password_set", "slack_webhook_url_set",
            "mattermost_webhook_url_set", "discord_webhook_url_set",
        ]

    def get_telegram_bot_token_set(self, obj) -> bool:
        return bool(obj.telegram_bot_token)

    def get_smtp_password_set(self, obj) -> bool:
        return bool(obj.smtp_password)

    def get_slack_webhook_url_set(self, obj) -> bool:
        return bool(obj.slack_webhook_url)

    def get_mattermost_webhook_url_set(self, obj) -> bool:
        return bool(obj.mattermost_webhook_url)

    def get_discord_webhook_url_set(self, obj) -> bool:
        return bool(obj.discord_webhook_url)

    def validate_slack_webhook_url(self, value):
        return validate_webhook_url(value)

    def validate_mattermost_webhook_url(self, value):
        return validate_webhook_url(value)

    def validate_discord_webhook_url(self, value):
        return validate_webhook_url(value)

    def validate_default_loan_days(self, value):
        if value < 1:
            raise serializers.ValidationError("Default loan days must be at least 1.")
        return value

    def validate(self, attrs):
        validate_smtp_settings(attrs, self.instance)
        return attrs

    def update(self, instance, validated_data):
        missing = object()
        telegram_bot_token = validated_data.pop("telegram_bot_token", missing)
        smtp_password = validated_data.pop("smtp_password", missing)
        slack_webhook_url = validated_data.pop("slack_webhook_url", missing)
        mattermost_webhook_url = validated_data.pop("mattermost_webhook_url", missing)
        discord_webhook_url = validated_data.pop("discord_webhook_url", missing)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if telegram_bot_token is not missing:
            instance.set_telegram_bot_token(telegram_bot_token)
        if smtp_password is not missing:
            instance.set_smtp_password(smtp_password)
        if slack_webhook_url is not missing:
            instance.set_slack_webhook_url(slack_webhook_url)
        if mattermost_webhook_url is not missing:
            instance.set_mattermost_webhook_url(mattermost_webhook_url)
        if discord_webhook_url is not missing:
            instance.set_discord_webhook_url(discord_webhook_url)
        instance.save()
        return instance
