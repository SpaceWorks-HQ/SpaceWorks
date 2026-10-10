"""`/control/` surfaces for offsite destinations: credentials are write-only here too."""

from django import forms
from django.contrib import admin
from django.contrib import messages
from rest_framework.exceptions import ValidationError
from unfold.admin import ModelAdmin

from apps.audit import services as audit
from apps.backup.models import BackupDestination, BackupDestinationUpload
from apps.backup.serializers_offsite import BackupDestinationSerializer
from apps.backup.services_offsite import probe_destination, retire_destination
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
        payload = {field: cleaned[field] for field in self.Meta.fields if field in cleaned}
        for field in ("access_key_id", "secret_access_key"):
            if cleaned.get(f"new_{field}"):
                payload[field] = cleaned[f"new_{field}"]
        serializer = BackupDestinationSerializer(
            self.instance if self.instance.pk else None, data=payload
        )
        if not serializer.is_valid():
            for field, errors in serializer.errors.items():
                form_field = f"new_{field}" if field in {"access_key_id", "secret_access_key"} else field
                self.add_error(form_field if form_field in self.fields else None, list(errors))
        elif "prefix" in serializer.validated_data:
            cleaned["prefix"] = serializer.validated_data["prefix"]
        return cleaned


@admin.register(BackupDestination)
class BackupDestinationAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    form = BackupDestinationForm
    list_display = ("name", "bucket", "enabled", "retention_days", "last_success_at", "last_error_code", "retired_at")
    readonly_fields = ("created_by", "created_at", "updated_at", "retired_at", "last_success_at", "last_error_code")
    actions = ("test_destinations", "retire_destinations")

    def has_delete_permission(self, request, obj=None):
        # Retirement wipes secrets while preserving the protected journal.
        return False

    @admin.action(description="Test selected destinations", permissions=["change"])
    def test_destinations(self, request, queryset):
        for destination in queryset:
            if destination.retired_at is not None:
                self.message_user(request, f"{destination.name} is retired.", messages.WARNING)
                continue
            result = probe_destination(destination, request.user)
            self.message_user(
                request,
                f"{destination.name}: {'bytes verified' if result['ok'] else result['error_code']}",
                messages.SUCCESS if result["ok"] else messages.ERROR,
            )

    @admin.action(description="Retire selected destinations and wipe credentials", permissions=["change"])
    def retire_destinations(self, request, queryset):
        for destination in queryset:
            try:
                retire_destination(destination.pk, request.user)
            except ValidationError:
                self.message_user(request, f"{destination.name} is already retired.", messages.WARNING)
                continue
            self.message_user(request, f"Retired {destination.name}; remote copies remain.")

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
