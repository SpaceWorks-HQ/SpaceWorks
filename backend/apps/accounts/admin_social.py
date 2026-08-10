from django import forms
from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.accounts.login_methods import (
    superadmins_without_social,
    users_stranded_without_social,
)
from apps.accounts.models_login_methods import PlatformLoginMethods
from apps.accounts.models_oidc import OidcProvider
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


class PlatformLoginMethodsForm(forms.ModelForm):
    class Meta:
        model = PlatformLoginMethods
        fields = "__all__"

    def clean(self):
        """Refuse a switch-off that leaves somebody with no way in.

        Turning a method OFF is the dangerous direction, and the accounts it strands are
        precisely the ones forgot-password cannot recover — they have no usable password
        to reset. Raised as a form error with the remedy attached rather than as a model
        constraint, so the superadmin is told what to fix.
        """
        cleaned = super().clean()
        password = cleaned.get("password_enabled", True)
        social = cleaned.get("social_enabled", True)

        if not social:
            stranded = users_stranded_without_social()
            if stranded:
                raise forms.ValidationError(
                    f"Disabling social sign-in would lock out {len(stranded)} account(s) "
                    "whose only credential is an identity provider — they have no usable "
                    "password, so a password reset cannot recover them. Set a password "
                    "for those accounts first."
                )
        if not password:
            if not social:
                raise forms.ValidationError(
                    "Password and social sign-in cannot both be off: phone sign-in issues "
                    "member sessions only, so nobody could reach the staff console or "
                    "this page again."
                )
            stranded = superadmins_without_social()
            if stranded:
                raise forms.ValidationError(
                    f"Disabling password sign-in would lock out {len(stranded)} "
                    "superadmin(s) who have no linked identity provider — and this page "
                    "is the only place the switch can be turned back on. Link a provider "
                    "to those accounts first."
                )
        return cleaned


@admin.register(PlatformLoginMethods)
class PlatformLoginMethodsAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    """Which ways in this deployment offers. Platform-scoped, never a tenant feature."""

    form = PlatformLoginMethodsForm
    list_display = (
        "__str__", "password_enabled", "social_enabled", "phone_enabled",
        "self_registration_enabled",
    )

    def has_add_permission(self, request):
        return not PlatformLoginMethods.objects.exists()

    def has_delete_permission(self, request, obj=None):
        """Deleting the row would silently re-enable every method.

        `load()` reads an absent row as "nothing configured", which is every switch on —
        correct for a deployment that has never touched them, and a surprise for one that
        deliberately turned two off.
        """
        return False


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


@admin.register(OidcProvider)
class OidcProviderAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    """Deployment-configured OpenID Connect providers.

    Superadmin-only and platform-scoped, like the built-in providers and for the same
    reason: identity resolves before a makerspace is selected, so a per-tenant provider
    would be unreachable at token-verification time.
    """

    list_display = ("display_name", "slug", "issuer", "is_enabled", "allow_auto_link")
    list_filter = ("is_enabled", "allow_auto_link")
    search_fields = ("slug", "display_name", "issuer")
    readonly_fields = ("created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        """Deleting the provider row would orphan every SocialIdentity that names it.

        Those users would keep a stored identity pointing at a provider the deployment
        can no longer resolve, and any who never set a password could not recover --
        the same lockout `social_lockout` refuses for the built-ins. Disable it instead:
        the row stays, the login stops, and re-enabling restores it.
        """
        return False
