from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import User
from apps.backup.custody import RECIPIENT_FLOOR, with_makerspace_custody_lock
from apps.integrations.email import platform_email_configured
from apps.makerspaces import domain_verification
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceArchiveRequest,
    default_branding_config,
)


_DISABLE_ACCESS_SEQUENCE = (
    "Enrol and verify at least two archive recipients before disabling "
    "superadmin access."
)


class MakerspaceMutationMixin:
    @transaction.atomic
    def create(self, validated_data):
        public_display_name = validated_data.pop("public_display_name", None)
        if public_display_name is not None:
            branding = default_branding_config()
            branding["display_name"] = public_display_name
            validated_data["branding_config"] = branding
        instance = super().create(validated_data)
        if domain_verification.is_self_host() and instance.frontend_domain:
            instance.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
            instance.domain_verified_at = timezone.now()
            instance.save(
                update_fields=[
                    "frontend_domain_status",
                    "domain_verified_at",
                    "updated_at",
                ]
            )
        with with_makerspace_custody_lock(instance.pk) as custody:
            instance = custody.makerspace
        return instance

    def update(self, instance, validated_data):
        missing = object()
        telegram_bot_token = validated_data.pop("telegram_bot_token", missing)
        smtp_password = validated_data.pop("smtp_password", missing)
        slack_webhook_url = validated_data.pop("slack_webhook_url", missing)
        mattermost_webhook_url = validated_data.pop("mattermost_webhook_url", missing)
        discord_webhook_url = validated_data.pop("discord_webhook_url", missing)
        public_display_name = validated_data.pop("public_display_name", missing)
        new_flag = validated_data.pop("superadmin_access_enabled", None)

        with with_makerspace_custody_lock(instance.pk) as custody:
            locked = custody.makerspace
            old_domain = locked.frontend_domain
            actor = self.context["request"].user
            is_superadmin = actor.is_superuser or actor.role == User.Role.SUPERADMIN
            if new_flag is not None and new_flag != locked.superadmin_access_enabled:
                self._validate_access_change(
                    custody, locked, new_flag, is_superadmin
                )
                locked.superadmin_access_enabled = new_flag
            for field, value in validated_data.items():
                setattr(locked, field, value)
            if (
                "frontend_domain" in validated_data
                and validated_data["frontend_domain"] != old_domain
            ):
                self._apply_frontend_domain_change(
                    locked, validated_data["frontend_domain"], is_superadmin
                )
            if public_display_name is not missing:
                branding = dict(locked.branding_config or {})
                branding["display_name"] = public_display_name
                locked.branding_config = branding
            if telegram_bot_token is not missing:
                locked.set_telegram_bot_token(telegram_bot_token)
            if smtp_password is not missing:
                locked.set_smtp_password(smtp_password)
            if slack_webhook_url is not missing:
                locked.set_slack_webhook_url(slack_webhook_url)
            if mattermost_webhook_url is not missing:
                locked.set_mattermost_webhook_url(mattermost_webhook_url)
            if discord_webhook_url is not missing:
                locked.set_discord_webhook_url(discord_webhook_url)
            locked.save()
            return locked

    def _validate_access_change(self, custody, locked, new_flag, is_superadmin):
        if new_flag is True and is_superadmin:
            raise serializers.ValidationError(
                {
                    "superadmin_access_enabled": (
                        "Only the makerspace admin can re-enable superadmin access."
                    )
                }
            )
        if new_flag is not False:
            return
        if (
            MakerspaceArchiveRequest.objects.select_for_update()
            .filter(
                makerspace=locked,
                status=MakerspaceArchiveRequest.Status.PENDING,
            )
            .exists()
        ):
            raise serializers.ValidationError(
                {
                    "superadmin_access_enabled": (
                        "Withdraw the pending archive request before disabling "
                        "superadmin access."
                    )
                }
            )
        if not platform_email_configured():
            raise serializers.ValidationError(
                {
                    "superadmin_access_enabled": (
                        "Configure Platform Email before disabling superadmin access, "
                        "so password recovery remains possible."
                    )
                }
            )
        if custody.verified_recipient_count() < RECIPIENT_FLOOR:
            raise serializers.ValidationError(
                {"superadmin_access_enabled": _DISABLE_ACCESS_SEQUENCE}
            )

    @staticmethod
    def _apply_frontend_domain_change(locked, frontend_domain, is_superadmin):
        if (
            domain_verification.is_self_host()
            and frontend_domain
            and not is_superadmin
        ):
            raise serializers.ValidationError(
                {
                    "frontend_domain": (
                        "Only a superadmin can set the custom domain on a "
                        "self-hosted instance."
                    )
                }
            )
        locked.frontend_domain_changed_at = timezone.now()
        if domain_verification.is_self_host() and frontend_domain:
            locked.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
            locked.domain_verified_at = timezone.now()
        else:
            locked.frontend_domain_status = Makerspace.DomainStatus.PENDING
            locked.domain_verified_at = None
