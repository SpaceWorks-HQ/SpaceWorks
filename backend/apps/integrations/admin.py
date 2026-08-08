from django import forms
from django.contrib import admin

from config.admin_access import SuperuserOnlyModelAdmin

from apps.integrations import admin_email_templates  # noqa: F401
from apps.integrations import admin_destinations  # noqa: F401
from apps.integrations import admin_email_logs  # noqa: F401
from apps.integrations import admin_notification_mutes  # noqa: F401
from apps.integrations import admin_notifications  # noqa: F401
from apps.integrations import admin_push  # noqa: F401
from apps.integrations import admin_recipients  # noqa: F401
from apps.integrations import admin_sms  # noqa: F401
from apps.integrations.models import PlatformEmailSettings
from apps.integrations.smtp_validation import validate_smtp_settings


class PlatformEmailSettingsAdminForm(forms.ModelForm):
    class Meta:
        model = PlatformEmailSettings
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        validate_smtp_settings(cleaned, self.instance)
        return cleaned

@admin.register(PlatformEmailSettings)
class PlatformEmailSettingsAdmin(SuperuserOnlyModelAdmin, admin.ModelAdmin):
    form = PlatformEmailSettingsAdminForm
    list_display = ("smtp_host", "smtp_port", "from_email", "updated_at")
    # smtp_password holds the Fernet-encrypted value; never edit it as raw ciphertext
    # in the admin. The React superadmin Platform Email panel is the write surface.
    exclude = ("smtp_password",)
    readonly_fields = ("updated_at",)

