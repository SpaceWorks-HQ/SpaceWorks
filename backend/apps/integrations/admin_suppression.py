"""Platform-only bounce/complaint control; tenant controls live in the staff API."""

from django import forms
from django.contrib import admin
from django.db import transaction

from apps.audit import services as audit
from apps.integrations.email_preferences import address_hash
from apps.integrations.models_suppression import EmailSuppression
from config.admin_access import SuperuserOnlyModelAdmin


class PlatformSuppressionForm(forms.ModelForm):
    address = forms.EmailField(help_text="Stored as a keyed hash; the address is never retained.")

    class Meta:
        model = EmailSuppression
        fields = ("reason",)

    def clean(self):
        cleaned = super().clean()
        address = cleaned.get("address")
        if address:
            self.instance.makerspace = None
            self.instance.address_hash = address_hash(None, address)
            if EmailSuppression.objects.filter(
                makerspace__isnull=True, address_hash=self.instance.address_hash,
            ).exists():
                self.add_error("address", "This platform address is already suppressed.")
        return cleaned


@admin.register(EmailSuppression)
class PlatformSuppressionAdmin(SuperuserOnlyModelAdmin, admin.ModelAdmin):
    form = PlatformSuppressionForm
    list_display = ("id", "reason", "created_by", "created_at")
    list_filter = ("reason",)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(makerspace__isnull=True)

    def get_fields(self, request, obj=None):
        return ("reason", "address_hash", "created_by", "created_at") if obj else ("address", "reason")

    def get_readonly_fields(self, request, obj=None):
        return self.get_fields(request, obj) if obj else ()

    def has_change_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.makerspace = None
        obj.created_by = request.user
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            audit.record(request.user, "email.platform_suppressed", target=obj,
                         meta={"reason": obj.reason})

    def delete_model(self, request, obj):
        with transaction.atomic():
            audit.record(request.user, "email.platform_unsuppressed", target=obj)
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            for obj in queryset:
                self.delete_model(request, obj)
