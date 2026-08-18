from rest_framework import serializers

from apps.integrations.models_destinations import (
    NotificationDestination,
    WEBHOOK_CHANNELS,
)
from apps.integrations.notification_enums import ChatNotificationChannel
from apps.integrations.webhook_validation import validate_webhook_url


class DestinationScopeSerializer(serializers.Serializer):
    machine_type_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )
    machine_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    category_ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class NotificationDestinationSerializer(serializers.ModelSerializer):
    # The credential is NEVER echoed. A webhook URL is a bearer secret: anyone who reads
    # it can post into the room. `credential_set` is what the console renders instead, the
    # same contract as the makerspace `*_set` booleans it replaces.
    credential_set = serializers.SerializerMethodField()
    scope = serializers.SerializerMethodField()

    class Meta:
        model = NotificationDestination
        fields = (
            "id",
            "channel",
            "label",
            "telegram_chat_id",
            "is_active",
            "credential_set",
            "scope",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_credential_set(self, obj):
        return bool(obj.webhook_url or obj.telegram_chat_id)

    def get_scope(self, obj):
        return {
            "machine_type_ids": [row.machine_type_id for row in obj.machine_type_scopes.all()],
            "machine_ids": [row.machine_id for row in obj.machine_scopes.all()],
            "category_ids": [row.category_id for row in obj.category_scopes.all()],
        }


class NotificationDestinationWriteSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=ChatNotificationChannel.choices)
    label = serializers.CharField(max_length=80)
    # Write-only, and optional on update so an edit that only renames a room does not have
    # to re-enter a secret the caller cannot read back.
    webhook_url = serializers.CharField(
        required=False, allow_blank=True, write_only=True, max_length=2000
    )
    telegram_chat_id = serializers.CharField(
        required=False, allow_blank=True, max_length=64
    )
    is_active = serializers.BooleanField(required=False, default=True)
    scope = DestinationScopeSerializer(required=False)

    def validate(self, attrs):
        channel = attrs["channel"]
        chat_id = (attrs.get("telegram_chat_id") or "").strip()
        webhook = (attrs.get("webhook_url") or "").strip()
        existing = self.context.get("instance")
        has_stored_webhook = bool(existing.webhook_url) if existing else False

        if channel == ChatNotificationChannel.TELEGRAM:
            if not chat_id:
                raise serializers.ValidationError(
                    {"telegram_chat_id": "A Telegram destination needs a chat id."}
                )
            if webhook:
                raise serializers.ValidationError(
                    {"webhook_url": "Telegram destinations use a chat id, not a webhook."}
                )
        elif channel in WEBHOOK_CHANNELS:
            if not (webhook or has_stored_webhook):
                raise serializers.ValidationError(
                    {"webhook_url": "This channel needs an incoming-webhook URL."}
                )
            if chat_id:
                raise serializers.ValidationError(
                    {"telegram_chat_id": "Only Telegram destinations carry a chat id."}
                )
            if webhook:
                attrs["webhook_url"] = validate_webhook_url(webhook)
        if existing is not None and existing.channel != channel:
            # Changing a room's channel would leave a credential of the wrong shape and
            # silently repoint an operator's scope links at a different provider.
            raise serializers.ValidationError(
                {"channel": "A destination's channel cannot be changed."}
            )
        return attrs
