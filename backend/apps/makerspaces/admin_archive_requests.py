from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.exceptions import ValidationError as DjangoValidationError
from django.template.response import TemplateResponse
from rest_framework.exceptions import APIException
from unfold.admin import ModelAdmin

from apps.makerspaces import archive_requests
from apps.makerspaces.models import MakerspaceArchiveRequest
from config.admin_access import SuperuserOnlyModelAdmin


@admin.register(MakerspaceArchiveRequest)
class MakerspaceArchiveRequestAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    actions = ["approve_selected", "decline_selected"]
    list_display = (
        "makerspace",
        "status",
        "requested_by",
        "requested_at",
        "resolved_by",
        "resolved_at",
    )
    list_filter = ("status", "makerspace")
    search_fields = ("makerspace__name", "makerspace__slug", "requested_by__username")
    readonly_fields = (
        "makerspace",
        "requested_by",
        "requested_at",
        "reason",
        "status",
        "resolved_by",
        "resolved_at",
        "resolution_note",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Approve selected archive requests")
    def approve_selected(self, request, queryset):
        # Approving IS archiving, so it must show the same unsettled-charge impact the direct
        # archive action shows. Without this a superadmin could archive from this changelist
        # while never seeing the owned/routed pending charges that the other route puts in
        # front of them -- two ways to do one thing, one of them uninformed.
        from apps.makerspaces import lifecycle

        rows = list(queryset.select_related("makerspace"))
        if "confirm_archive_requests" not in request.POST:
            context = {
                **self.admin_site.each_context(request),
                "title": "Approve selected archive requests",
                "requests": [
                    {
                        "object": archive_request,
                        **lifecycle.archive_impact(archive_request.makerspace),
                    }
                    for archive_request in rows
                ],
                "opts": self.model._meta,
                "action_name": "approve_selected",
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
            }
            return TemplateResponse(
                request,
                "admin/makerspaces/archive_request_approve_confirmation.html",
                context,
            )

        approved = 0
        for archive_request in rows:
            try:
                archive_requests.approve(archive_request, request.user)
            except (APIException, DjangoValidationError) as exc:
                self.message_user(
                    request,
                    f"{archive_request.pk}: {_error_detail(exc)}",
                    level=messages.ERROR,
                )
            else:
                approved += 1
        if approved:
            self.message_user(
                request,
                f"Approved {approved} archive request(s).",
                level=messages.SUCCESS,
            )

    @admin.action(description="Decline selected archive requests")
    def decline_selected(self, request, queryset):
        selected = list(queryset.select_related("makerspace"))
        if "confirm_decline" not in request.POST:
            return TemplateResponse(
                request,
                "admin/makerspaces/archive_request_decline_confirmation.html",
                {
                    **self.admin_site.each_context(request),
                    "title": "Decline selected archive requests",
                    "archive_requests": selected,
                    "opts": self.model._meta,
                    "action_name": "decline_selected",
                    "action_checkbox_name": ACTION_CHECKBOX_NAME,
                },
            )

        declined = 0
        note = request.POST.get("resolution_note", "")
        for archive_request in selected:
            try:
                archive_requests.decline(archive_request, request.user, note)
            except (APIException, DjangoValidationError) as exc:
                self.message_user(
                    request,
                    f"{archive_request.pk}: {_error_detail(exc)}",
                    level=messages.ERROR,
                )
            else:
                declined += 1
        if declined:
            self.message_user(
                request,
                f"Declined {declined} archive request(s).",
                level=messages.SUCCESS,
            )


def _error_detail(exc):
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        return detail.get("detail") or next(iter(detail.values()))
    if detail:
        return detail
    return getattr(exc, "message", None) or str(exc)
