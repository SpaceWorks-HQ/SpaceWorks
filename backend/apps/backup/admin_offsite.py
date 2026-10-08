"""`/control/` surfaces for offsite destinations: credentials are write-only here too."""

from django import forms
from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.audit import services as audit
from apps.backup.models import BackupDestination, BackupDestinationUpload
from config.admin_access import SuperuserOnlyModelAdmin


class BackupDestinationForm(forms.ModelForm):
    new_access_key_id = forms.CharField(
        required=False, label="Access key id", widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to keep the stored value.",
    )
    new_secret_access_key = forms.CharField(
        required=False, label="Secret access key", strip=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to keep the stored value.",
    )

    class Meta:
        model = BackupDestination
        fields = (
            "name", "endpoint_url", "bucket", "region", "prefix", "addressing_style",
            "enabled", "retention_days",
        )

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk is None and not (
            cleaned.get("new_access_key_id") and cleaned.get("new_secret_access_key")
        ):
            raise forms.ValidationError("Both credentials are required for a new destination.")
        if self.instance.retired_at is not None:
            raise forms.ValidationError("A retired destination cannot be changed.")
        return cleaned


@admin.register(BackupDestination)
class BackupDestinationAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    form = BackupDestinationForm
    list_display = ("name", "bucket", "enabled", "retention_days", "last_success_at", "last_error_code", "retired_at")
    readonly_fields = ("created_by", "created_at", "updated_at", "retired_at", "last_success_at", "last_error_code")

    def has_delete_permission(self, request, obj=None):
        # The journal PROTECTs its destination; retire through the API instead.
        return False

    def save_model(self, request, obj, form, change):
        changed = []
        for field, setter in (
            ("new_access_key_id", obj.set_access_key_id),
            ("new_secret_access_key", obj.set_secret_access_key),
        ):
            raw = form.cleaned_data.get(field)
            if raw:
                setter(raw)
                changed.append(field.removeprefix("new_"))
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        audit.record(
            request.user,
            "backup.destination_updated" if change else "backup.destination_created",
            target=obj,
            meta={"via": "control", "fields": sorted(form.changed_data), "credentials_changed": changed},
        )


@admin.register(BackupDestinationUpload)
class BackupDestinationUploadAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("destination", "archive_id_snapshot", "scope_snapshot", "state", "attempts", "verified_at", "expires_at", "last_error_code")
    list_filter = ("destination", "state", "scope_snapshot")
    readonly_fields = tuple(field.name for field in BackupDestinationUpload._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
