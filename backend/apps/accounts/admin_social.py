from django import forms
from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.accounts.models_social import (
    PlatformSocialAuthSettings,
    SocialIdentity,
    SocialProvider,
)
from apps.accounts.social_lockout import (
    GOOGLE_FIELDS,
    provider_configured,
    users_locked_out_by_disabling,
)
from config.admin_access import SuperuserOnlyModelAdmin


class PlatformSocialAuthSettingsForm(forms.ModelForm):
    apple_private_key_raw = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Write-only. Leave blank to keep the current encrypted Apple key.",
    )

    class Meta:
        model = PlatformSocialAuthSettings
        exclude = ("apple_private_key",)

    def clean(self):
        # Turning a provider OFF is the dangerous direction: accounts created through it
        # that never set a password have no other way in, and forgot-password cannot
        # help them (there is no usable password to reset). Checked here rather than in
        # the model so the superadmin sees it as a form error with the remedy attached.
        cleaned = super().clean()
        stored = PlatformSocialAuthSettings.objects.filter(pk=1).first()
        incoming = PlatformSocialAuthSettings(
            **{
                field: cleaned.get(field, getattr(stored, field, "") if stored else "")
                for field in (*GOOGLE_FIELDS, "apple_service_id", "apple_native_app_ids")
            }
        )
        for provider in (SocialProvider.GOOGLE, SocialProvider.APPLE):
            if not provider_configured(stored, provider):
                continue
            if provider_configured(incoming, provider):
                continue
            stranded = users_locked_out_by_disabling(provider)
            if stranded:
                raise forms.ValidationError(
                    f"Disabling {provider.label} would lock out {len(stranded)} "
                    f"account(s) whose only credential is {provider.label} — they have "
                    "no usable password, so a password reset cannot recover them. Set a "
                    "password for those accounts (or link another provider) first."
                )
        return cleaned

    def save(self, commit=True):
        row = super().save(commit=False)
        if self.cleaned_data.get("apple_private_key_raw"):
            row.set_apple_private_key(self.cleaned_data["apple_private_key_raw"])
        if commit:
            row.save()
            from apps.accounts.social_csp import clear_social_csp_cache

            clear_social_csp_cache()
        return row


@admin.register(PlatformSocialAuthSettings)
class PlatformSocialAuthSettingsAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    form = PlatformSocialAuthSettingsForm

    def has_add_permission(self, request):
        return not PlatformSocialAuthSettings.objects.exists()


@admin.register(SocialIdentity)
class SocialIdentityAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("id", "user", "provider", "created_at")
    readonly_fields = ("user", "provider", "provider_sub", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
