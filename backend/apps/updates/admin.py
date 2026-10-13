from django.contrib import admin
from django import forms
from django.db import transaction

from apps.separability.tombstones import app_is_tombstoned
from config.admin_access import SuperuserOnlyModelAdmin
from config.admin_audit import AuditedControlChangeMixin

from apps.updates.models import PlatformUpdateSettings
from apps.updates import services


class PlatformUpdateSettingsForm(forms.ModelForm):
    class Meta:
        model = PlatformUpdateSettings
        fields = ("automatic_updates_enabled",)


class PlatformUpdateSettingsAdmin(AuditedControlChangeMixin, SuperuserOnlyModelAdmin, admin.ModelAdmin):
    form = PlatformUpdateSettingsForm
    audit_action = "platform.update_settings_updated"
    list_display = (
        "automatic_updates_enabled",
        "status",
        "current_version",
        "available_version",
        "last_checked_at",
    )
    readonly_fields = (
        "status",
        "current_version",
        "available_version",
        "target_version",
        "update_requested_at",
        "last_checked_at",
        "last_updated_at",
        "last_backup_at",
        "last_backup_name",
        "last_error",
        "updated_at",
        "release_notes",
        "release_url",
        "running_since",
        "pre_update_version",
        "pre_update_archive",
        "rollback_restore",
    )

    def has_add_permission(self, request):
        return not PlatformUpdateSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        # Re-read under a row lock: the host may have claimed an update after form validation.
        row = services._locked_settings()
        row.automatic_updates_enabled = form.cleaned_data["automatic_updates_enabled"]
        super().save_model(request, row, form, change)
        # Django continues logging/redirecting with the original form object.
        obj.pk = row.pk
        obj._state = row._state
        form.instance = row


# See the note in apps/payments/admin.py: autodiscovery runs before ready(), so this must
# read the setting rather than the runtime manifest.
if not app_is_tombstoned("updates"):
    admin.site.register(PlatformUpdateSettings, PlatformUpdateSettingsAdmin)
