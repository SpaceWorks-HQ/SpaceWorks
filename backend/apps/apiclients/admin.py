import secrets

from django.contrib import admin, messages
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DRFValidationError
from unfold.admin import ModelAdmin
from apps.apiclients.models import ApiClient, ApiKeyRequest
from apps.apiclients.admin_forms import ApiClientAdminForm
from apps.apiclients.notifications import notify_api_key_request_resolved
from apps.apiclients.services import sync_makerspace_origins
from apps.audit import services as audit
from apps.makerspaces import limits
from config.admin_access import SuperuserOnlyModelAdmin



@admin.register(ApiClient)
class ApiClientAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    form = ApiClientAdminForm
    list_display = (
        "label",
        "client_id",
        "makerspace",
        "makerspace_public_code",
        "is_active",
        "last_seen_at",
        "last_seen_ip",
        "created_at",
    )
    list_filter = ("is_active", "makerspace")
    readonly_fields = (
        "client_id",
        "makerspace_public_code",
        "makerspace_public_api_key",
        "created_by",
        "last_seen_at",
        "last_seen_ip",
        "created_at",
        "updated_at",
    )
    fields = (
        "label",
        "makerspace",
        "allowed_origins",
        "is_active",
        "telegram_group_chat_id",
        "telegram_bot_token",
        "smtp_host",
        "smtp_port",
        "smtp_username",
        "smtp_password",
        "smtp_use_tls",
        "smtp_use_ssl",
        "smtp_from_email",
        "client_id",
        "makerspace_public_code",
        "makerspace_public_api_key",
        "created_by",
        "last_seen_at",
        "last_seen_ip",
        "created_at",
        "updated_at",
    )

    # Generate + reveal the secret once at creation.
    def save_model(self, request, obj, form, change):
        new_secret = None
        if not change:
            obj.created_by = request.user
            new_secret = secrets.token_urlsafe(32)
            obj.set_secret(new_secret)
        super().save_model(request, obj, form, change)
        self._save_makerspace_settings(obj, form)
        sync_makerspace_origins(obj.makerspace)
        if new_secret:
            messages.warning(
                request,
                f"Client secret for {obj.client_id} (shown once - copy it now): {new_secret}",
            )

    def delete_model(self, request, obj):
        makerspace = obj.makerspace
        super().delete_model(request, obj)
        sync_makerspace_origins(makerspace)

    def delete_queryset(self, request, queryset):
        makerspaces = list({client.makerspace for client in queryset.select_related("makerspace")})
        super().delete_queryset(request, queryset)
        for makerspace in makerspaces:
            sync_makerspace_origins(makerspace)

    def _save_makerspace_settings(self, obj, form):
        if not obj.makerspace_id:
            return
        makerspace = obj.makerspace
        text_fields = [
            "telegram_group_chat_id",
            "smtp_host",
            "smtp_username",
            "smtp_from_email",
        ]
        for field in text_fields:
            setattr(makerspace, field, form.cleaned_data.get(field) or "")
        if form.cleaned_data.get("telegram_bot_token"):
            makerspace.set_telegram_bot_token(form.cleaned_data["telegram_bot_token"])
        if form.cleaned_data.get("smtp_password"):
            makerspace.set_smtp_password(form.cleaned_data["smtp_password"])
        makerspace.smtp_port = form.cleaned_data.get("smtp_port") or 587
        makerspace.smtp_use_tls = bool(form.cleaned_data.get("smtp_use_tls"))
        makerspace.smtp_use_ssl = bool(form.cleaned_data.get("smtp_use_ssl"))
        makerspace.save(
            update_fields=[
                *text_fields,
                "telegram_bot_token",
                "smtp_password",
                "smtp_port",
                "smtp_use_tls",
                "smtp_use_ssl",
                "updated_at",
            ]
        )

    @admin.display(description="Makerspace code")
    def makerspace_public_code(self, obj):
        return obj.makerspace.public_code if obj.makerspace_id else "-"

    @admin.display(description="Legacy public API key")
    def makerspace_public_api_key(self, obj):
        return obj.makerspace.public_api_key if obj.makerspace_id else "-"


@admin.register(ApiKeyRequest)
class ApiKeyRequestAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    actions = ["approve_and_issue", "reject_selected"]
    list_display = ("label", "makerspace", "requester", "status", "created_at")
    list_filter = ("status", "makerspace")
    readonly_fields = (
        "requester",
        "created_at",
        "updated_at",
        "resolved_by",
        "resolved_at",
    )
    search_fields = ("label",)

    @admin.action(description="Approve selected API key requests and issue clients")
    def approve_and_issue(self, request, queryset):
        approved_count = 0
        skipped_count = 0
        for api_key_request in queryset.select_related("makerspace", "requester"):
            if api_key_request.status != ApiKeyRequest.Status.PENDING:
                skipped_count += 1
                continue

            try:
                with transaction.atomic():
                    limits.check_quota(
                        api_key_request.makerspace,
                        "api_clients",
                        adding=1,
                    )
                    client, raw_secret = ApiClient.issue(
                        label=api_key_request.label,
                        makerspace=api_key_request.makerspace,
                        allowed_origins=api_key_request.allowed_origins or [],
                        created_by=request.user,
                        client_type="server",
                    )
            except DRFValidationError as exc:
                self.message_user(
                    request,
                    f"{api_key_request.pk}: {exc.detail}",
                    level=messages.ERROR,
                )
                continue
            except DjangoValidationError as exc:
                self.message_user(
                    request,
                    (
                        f"{api_key_request.pk}: "
                        f"{getattr(exc, 'message_dict', exc.messages)}"
                    ),
                    level=messages.ERROR,
                )
                continue
            sync_makerspace_origins(api_key_request.makerspace)
            api_key_request.status = ApiKeyRequest.Status.APPROVED
            api_key_request.resolved_by = request.user
            api_key_request.resolved_at = timezone.now()
            api_key_request.save(
                update_fields=[
                    "status",
                    "resolved_by",
                    "resolved_at",
                    "updated_at",
                ]
            )
            audit.record(
                request.user,
                "api_key_request.approved",
                makerspace=api_key_request.makerspace,
                target=api_key_request,
                meta={"api_client_id": client.pk},
            )
            audit.record(
                request.user,
                "api_client.created",
                makerspace=client.makerspace,
                target=client,
                meta={
                    "allowed_origins": client.allowed_origins,
                    "api_key_request_id": api_key_request.pk,
                },
            )
            self.message_user(
                request,
                (
                    f"Client secret for {client.client_id} "
                    f"(shown once - copy it now): {raw_secret}"
                ),
                level=messages.WARNING,
            )
            notify_api_key_request_resolved(api_key_request)
            approved_count += 1

        if approved_count:
            self.message_user(
                request,
                f"Approved {approved_count} API key request(s).",
                level=messages.SUCCESS,
            )
        if skipped_count:
            self.message_user(
                request,
                f"Skipped {skipped_count} non-pending API key request(s).",
                level=messages.WARNING,
            )

    @admin.action(description="Reject selected API key requests")
    def reject_selected(self, request, queryset):
        rejected_count = 0
        skipped_count = 0
        for api_key_request in queryset.select_related("makerspace", "requester"):
            if api_key_request.status != ApiKeyRequest.Status.PENDING:
                skipped_count += 1
                continue

            api_key_request.status = ApiKeyRequest.Status.REJECTED
            api_key_request.resolved_by = request.user
            api_key_request.resolved_at = timezone.now()
            api_key_request.save(
                update_fields=[
                    "status",
                    "resolved_by",
                    "resolved_at",
                    "updated_at",
                ]
            )
            audit.record(
                request.user,
                "api_key_request.rejected",
                makerspace=api_key_request.makerspace,
                target=api_key_request,
            )
            notify_api_key_request_resolved(api_key_request)
            rejected_count += 1

        if rejected_count:
            self.message_user(
                request,
                f"Rejected {rejected_count} API key request(s).",
                level=messages.SUCCESS,
            )
        if skipped_count:
            self.message_user(
                request,
                f"Skipped {skipped_count} non-pending API key request(s).",
                level=messages.WARNING,
            )
