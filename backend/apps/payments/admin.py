from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction
from unfold.admin import ModelAdmin

from apps.audit import services as audit
from apps.payments.credential_validation import (
    RAW_CREDENTIAL_FIELDS,
    raw_credential_is_unreadable,
    update_payment_settings,
    update_platform_payment_settings,
    validate_platform_credential_changes,
    validate_raw_credential_changes,
)
from apps.payments.models import (
    MakerspacePaymentSettings,
    PlatformStripeConnectSettings,
)
from apps.separability.tombstones import app_is_tombstoned
from config.admin_access import SuperuserOnlyModelAdmin


class MakerspacePaymentSettingsAdminForm(forms.ModelForm):
    stripe_publishable_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to retain the existing publishable key.",
    )
    stripe_secret_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to retain the existing secret key.",
    )
    stripe_webhook_secret = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to retain the existing webhook secret.",
    )

    class Meta:
        model = MakerspacePaymentSettings
        fields = (
            "makerspace",
            "stripe_publishable_key",
            "stripe_secret_key",
            "stripe_webhook_secret",
            "default_currency",
        )

    def save(self, commit=True):
        settings = super().save(commit=False)
        if commit:
            return update_payment_settings(settings, self.payment_setting_changes())
        return settings

    def payment_setting_changes(self):
        changes = {
            "makerspace": self.cleaned_data["makerspace"],
            "default_currency": self.cleaned_data["default_currency"],
        }
        for field in (
            "stripe_publishable_key",
            "stripe_secret_key",
            "stripe_webhook_secret",
        ):
            if self.cleaned_data[field] or field in getattr(
                self, "_unreadable_raw_fields", ()
            ):
                changes[field] = self.cleaned_data[field]
        return changes

    def clean(self):
        cleaned_data = super().clean()
        self._unreadable_raw_fields = {
            field
            for field in RAW_CREDENTIAL_FIELDS
            if raw_credential_is_unreadable(self.instance, field)
        }
        credential_changes = {
            field: cleaned_data[field]
            for field in RAW_CREDENTIAL_FIELDS
            if cleaned_data.get(field)
            or field in self._unreadable_raw_fields
        }
        try:
            validate_raw_credential_changes(self.instance, credential_changes)
        except ValidationError as exc:
            for field, messages in exc.message_dict.items():
                self.add_error(field, messages)
        return cleaned_data


class MakerspacePaymentSettingsAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    form = MakerspacePaymentSettingsAdminForm
    list_display = ("makerspace", "configured", "default_currency")
    list_filter = ("makerspace",)
    search_fields = ("makerspace__name", "makerspace__slug", "makerspace__public_code")

    @admin.display(boolean=True, description="Configured")
    def configured(self, obj):
        return obj.is_configured

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST" or object_id is None:
            return super().changeform_view(request, object_id, form_url, extra_context)
        with transaction.atomic():
            # Hold the same settings-first lock across form validation and save.
            self.model.objects.select_for_update().get(pk=object_id)
            return super().changeform_view(
                request, object_id, form_url, extra_context
            )

    def save_model(self, request, obj, form, change):
        updated = update_payment_settings(obj, form.payment_setting_changes())
        for field in obj._meta.concrete_fields:
            setattr(obj, field.attname, getattr(updated, field.attname))


class PlatformStripeConnectSettingsAdminForm(forms.ModelForm):
    stripe_publishable_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to retain the existing platform publishable key.",
    )
    stripe_secret_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to retain the existing platform secret key.",
    )
    stripe_webhook_secret = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to retain the existing platform webhook secret.",
    )

    class Meta:
        model = PlatformStripeConnectSettings
        fields = (
            "stripe_publishable_key",
            "stripe_secret_key",
            "stripe_webhook_secret",
            "stripe_connect_client_id",
            "application_fee_bps",
        )

    def save(self, commit=True):
        connect_settings = super().save(commit=False)
        if commit:
            return update_platform_payment_settings(
                connect_settings, self.payment_setting_changes()
            )
        return connect_settings

    def payment_setting_changes(self):
        changes = {
            "stripe_connect_client_id": self.cleaned_data[
                "stripe_connect_client_id"
            ],
            "application_fee_bps": self.cleaned_data["application_fee_bps"],
        }
        for field in (
            "stripe_publishable_key",
            "stripe_secret_key",
            "stripe_webhook_secret",
        ):
            if self.cleaned_data[field]:
                changes[field] = self.cleaned_data[field]
        return changes

    def clean(self):
        cleaned_data = super().clean()
        credential_changes = {
            field: cleaned_data[field]
            for field in RAW_CREDENTIAL_FIELDS
            if cleaned_data.get(field)
        }
        try:
            validate_platform_credential_changes(self.instance, credential_changes)
        except ValidationError as exc:
            for field, messages in exc.message_dict.items():
                self.add_error(field, messages)
        return cleaned_data


class PlatformStripeConnectSettingsAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    form = PlatformStripeConnectSettingsAdminForm
    list_display = (
        "stripe_connect_client_id",
        "application_fee_bps",
        "updated_at",
    )

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not self.model.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method != "POST" or object_id is None:
            return super().changeform_view(request, object_id, form_url, extra_context)
        with transaction.atomic():
            # Hold the shared platform-first lock across form validation and save.
            self.model.objects.select_for_update().get(pk=object_id)
            return super().changeform_view(
                request, object_id, form_url, extra_context
            )

    def save_model(self, request, obj, form, change):
        changes = form.payment_setting_changes()
        updated = update_platform_payment_settings(obj, changes)
        audit.record(
            request.user,
            "platform.stripe_connect_settings_updated",
            target=updated,
            meta={"changed_fields": sorted(set(form.changed_data) & set(changes))},
        )
        for field in obj._meta.concrete_fields:
            setattr(obj, field.attname, getattr(updated, field.attname))


# Registered only while the deployment ships payments. `app_is_tombstoned` rather than
# `runtime_active` because django.contrib.admin autodiscovers every admin.py *before* the
# owning app's ready() has registered anything -- the manifest is not populated yet.
# The classes stay defined either way so the module still imports.
if not app_is_tombstoned("payments"):
    admin.site.register(MakerspacePaymentSettings, MakerspacePaymentSettingsAdmin)
    admin.site.register(PlatformStripeConnectSettings, PlatformStripeConnectSettingsAdmin)
