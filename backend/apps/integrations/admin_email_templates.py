from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.integrations.models import EmailTemplate, MachineTypeEmailTemplate
from apps.integrations.models_chat_templates import ChatTemplate
from config.admin_access import SuperuserOnlyModelAdmin


@admin.register(EmailTemplate)
class EmailTemplateAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = (
        "makerspace",
        "stream",
        "audience",
        "key",
        "is_active",
        "updated_at",
    )
    list_filter = ("stream", "audience", "key", "is_active", "makerspace")
    search_fields = ("subject", "text_body", "html_body", "makerspace__name")
    autocomplete_fields = ("makerspace",)
    readonly_fields = ("created_at", "updated_at")
    fields = (
        "makerspace",
        "stream",
        "audience",
        "key",
        "subject",
        "text_body",
        "html_body",
        "is_active",
        "created_at",
        "updated_at",
    )


@admin.register(MachineTypeEmailTemplate)
class MachineTypeEmailTemplateAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = (
        "makerspace",
        "machine_type",
        "stream",
        "audience",
        "key",
        "is_active",
        "updated_at",
    )
    list_filter = ("stream", "audience", "key", "is_active", "makerspace")
    search_fields = (
        "subject",
        "text_body",
        "html_body",
        "makerspace__name",
        "machine_type__name",
    )
    autocomplete_fields = ("makerspace", "machine_type")
    readonly_fields = ("created_at", "updated_at")
    fields = (
        "makerspace",
        "machine_type",
        "stream",
        "audience",
        "key",
        "subject",
        "text_body",
        "html_body",
        "is_active",
        "created_at",
        "updated_at",
    )


@admin.register(ChatTemplate)
class ChatTemplateAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    """One chat body per (feature, event), shared by all four chat channels.

    No `audience` column by design: chat is a staff surface, so there is only ever one
    audience to author for — see `chat_templates.render_chat_text`.
    """

    list_display = ("makerspace", "feature", "event", "is_active", "updated_at")
    list_filter = ("feature", "is_active", "makerspace")
    search_fields = ("event", "text_body", "makerspace__name")
    autocomplete_fields = ("makerspace",)
    readonly_fields = ("created_at", "updated_at")
