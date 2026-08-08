from django import forms
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from apps.integrations.models_destinations import (
    DestinationCategoryScope,
    DestinationMachineScope,
    DestinationMachineTypeScope,
    NotificationDestination,
    WEBHOOK_CHANNELS,
)
from apps.integrations.notification_enums import ChatNotificationChannel
from config.admin_access import SuperuserOnlyModelAdmin


class NotificationDestinationAdminForm(forms.ModelForm):
    # Write-only: the stored value is Fernet ciphertext, and echoing a decrypted webhook
    # into a form field would put a live credential in an HTML response and in the
    # browser's autofill. Leaving it blank keeps the existing credential.
    new_webhook_url = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to keep the current webhook URL.",
    )

    class Meta:
        model = NotificationDestination
        exclude = ("webhook_url",)

    def clean(self):
        cleaned = super().clean()
        channel = cleaned.get("channel")
        chat_id = (cleaned.get("telegram_chat_id") or "").strip()
        raw_webhook = (cleaned.get("new_webhook_url") or "").strip()
        has_webhook = bool(raw_webhook or self.instance.webhook_url)

        if channel == ChatNotificationChannel.TELEGRAM:
            if not chat_id:
                raise forms.ValidationError(
                    {"telegram_chat_id": "A Telegram destination needs a chat id."}
                )
            if raw_webhook:
                raise forms.ValidationError(
                    {"new_webhook_url": "Telegram destinations use a chat id, not a webhook."}
                )
        elif channel in WEBHOOK_CHANNELS:
            if not has_webhook:
                raise forms.ValidationError(
                    {"new_webhook_url": "This channel needs an incoming-webhook URL."}
                )
            if chat_id:
                raise forms.ValidationError(
                    {"telegram_chat_id": "Only Telegram destinations carry a chat id."}
                )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw_webhook = (self.cleaned_data.get("new_webhook_url") or "").strip()
        if raw_webhook:
            instance.set_webhook_url(raw_webhook)
        if instance.channel == ChatNotificationChannel.TELEGRAM:
            instance.webhook_url = ""
        else:
            instance.telegram_chat_id = ""
        if commit:
            instance.save()
        return instance


class DestinationMachineTypeScopeInline(TabularInline):
    model = DestinationMachineTypeScope
    extra = 0


class DestinationMachineScopeInline(TabularInline):
    model = DestinationMachineScope
    extra = 0


class DestinationCategoryScopeInline(TabularInline):
    model = DestinationCategoryScope
    extra = 0


@admin.register(NotificationDestination)
class NotificationDestinationAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    """A room a makerspace posts into. No scope links means space-wide."""

    form = NotificationDestinationAdminForm
    inlines = [
        DestinationMachineTypeScopeInline,
        DestinationMachineScopeInline,
        DestinationCategoryScopeInline,
    ]
    list_display = ("makerspace", "channel", "label", "is_active", "credential_set", "updated_at")
    list_filter = ("makerspace", "channel", "is_active")
    search_fields = ("label",)
    readonly_fields = ("created_at", "updated_at")

    @admin.display(boolean=True, description="Credential set")
    def credential_set(self, obj):
        return bool(obj.webhook_url or obj.telegram_chat_id)
