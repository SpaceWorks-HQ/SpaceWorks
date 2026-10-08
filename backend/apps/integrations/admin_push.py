from django import forms
from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.integrations.models_push import PlatformPushSettings, PushDevice
from config.admin_access import SuperuserOnlyModelAdmin
from config.admin_audit import AuditedControlChangeMixin


class PlatformPushSettingsForm(forms.ModelForm):
    fcm_service_account_raw = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False),
        help_text="Write-only. Leave blank to keep the current encrypted credential.",
    )
    apns_private_key_raw = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False),
        help_text="Write-only. Leave blank to keep the current encrypted key.",
    )
    clear_fcm_credentials = forms.BooleanField(required=False)
    clear_apns_credentials = forms.BooleanField(required=False)

    class Meta:
        model = PlatformPushSettings
        fields = ("apns_team_id", "apns_key_id", "apns_topic")

    def save(self, commit=True):
        row = super().save(commit=False)
        if self.cleaned_data.get("clear_fcm_credentials"):
            row.set_fcm_service_account("")
        elif self.cleaned_data.get("fcm_service_account_raw"):
            row.set_fcm_service_account(self.cleaned_data["fcm_service_account_raw"])
        if self.cleaned_data.get("clear_apns_credentials"):
            row.set_apns_private_key("")
        elif self.cleaned_data.get("apns_private_key_raw"):
            row.set_apns_private_key(self.cleaned_data["apns_private_key_raw"])
        if commit:
            row.save()
        return row


@admin.register(PlatformPushSettings)
class PlatformPushSettingsAdmin(AuditedControlChangeMixin, SuperuserOnlyModelAdmin, ModelAdmin):
    audit_action = "platform.push_settings_updated"
    form = PlatformPushSettingsForm
    fieldsets = ((None, {"fields": (
        "fcm_service_account_raw", "clear_fcm_credentials",
        "apns_private_key_raw", "clear_apns_credentials",
        "apns_team_id", "apns_key_id", "apns_topic", "updated_at",
    )}),)
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not PlatformPushSettings.objects.exists()


@admin.register(PushDevice)
class PushDeviceAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("id", "makerspace", "user", "provider", "environment", "active", "updated_at")
    list_filter = ("provider", "environment", "active")
    readonly_fields = (
        "user", "makerspace", "device_grant", "provider", "environment",
        "active", "invalidated_at", "created_at", "updated_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
