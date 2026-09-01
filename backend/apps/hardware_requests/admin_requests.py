from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from apps.hardware_requests.admin_workflow import WORKFLOW_EXCEPTIONS
from apps.hardware_requests.handover_workflow import (
    assign_box,
    set_return_due as workflow_set_return_due,
)
from apps.hardware_requests.admin_request_review import RequestReviewAdminMixin
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from config.admin_access import SuperuserOnlyModelAdmin
from apps.encryption.admin_search import ScopedPiiAdminSearchMixin


class ReturnDueForm(forms.Form):
    return_due_at = forms.DateTimeField(
        required=True,
        input_formats=[
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ],
    )


class HardwareRequestItemInline(TabularInline):
    model = HardwareRequestItem
    extra = 0
    can_delete = False
    readonly_fields = (
        "product",
        "requested_quantity",
        "accepted_quantity",
        "issued_quantity",
        "returned_quantity",
        "damaged_quantity",
        "missing_quantity",
    )
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(HardwareRequest)
class HardwareRequestAdmin(
    RequestReviewAdminMixin, ScopedPiiAdminSearchMixin, SuperuserOnlyModelAdmin, ModelAdmin
):
    # Accepting reserves stock and rejecting closes a person's ask, so neither is a
    # checkbox-column decision any more: both moved to the one-by-one review page
    # (`admin_request_review`). What survives here is genuinely bulk-shaped work on
    # requests whose decision has ALREADY been made.
    actions = [
        "assign_box_selected",
        "set_return_due",
    ]
    list_display = (
        "id",
        "status",
        "makerspace",
        "requester_identity",
        "return_due_at",
        "created_at",
        "review_link",
    )
    # `requester_contact_verified` is filterable so the unverified submissions -- which
    # are exactly the account-less ones -- can be pulled up as a group before handover.
    list_filter = ("status", "makerspace", "requester_contact_verified")
    search_fields = (
        "requested_for",
        "rejection_reason",
        "items__product__name",
    )
    readonly_fields = (
        "makerspace",
        "requester",
        "requester_username",
        "requester_contact_verified",
        "status",
        "requested_for",
        "rejection_reason",
        "accepted_by",
        "accepted_at",
        "assigned_box",
        "issued_by",
        "issued_at",
        "return_due_at",
        "return_reminder_sent_at",
        "closed_by",
        "closed_at",
        "public_token",
        "created_at",
        "updated_at",
    )
    fields = readonly_fields
    inlines = [HardwareRequestItemInline]
    pii_search_model = "hardware_requests.HardwareRequest"
    pii_search_fields = ("requester_name", "requester_contact_email")

    @admin.display(description="Requester")
    def requester_identity(self, obj):
        label = obj.requester_name or obj.requester_contact_email or "-"
        if obj.requester_contact_verified:
            return label
        # An account-less submitter typed this address themselves and nothing has ever
        # proved it is theirs -- staff acceptance does not prove it either. Marking it
        # here is what stops the queue from reading like a list of known people.
        return f"{label} (unverified contact)"

    @admin.display(description="Review")
    def review_link(self, obj):
        if obj.status != HardwareRequest.Status.PENDING_APPROVAL:
            return "-"
        url = reverse(
            "admin:hardware_requests_hardwarerequest_review", args=[obj.pk]
        )
        return format_html('<a href="{}">Review</a>', url)

    # Requests are created by the public submit flow and mutated only through the
    # workflow services. Direct add hits required readonly fields and direct delete
    # bypasses reservation/audit/notification cleanup.
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Assign box to selected requests")
    def assign_box_selected(self, request, queryset):
        if "apply" not in request.POST:
            return self._intermediate_action_response(
                request,
                queryset,
                "admin/hardware_requests/assign_box_action.html",
                "Assign boxes to selected hardware requests",
                "assign_box_selected",
            )

        success_count = 0
        for hardware_request in queryset:
            box_code = request.POST.get(f"box_code_{hardware_request.pk}", "").strip()
            try:
                assign_box(request.user, hardware_request, box_code)
            except WORKFLOW_EXCEPTIONS as exc:
                self.message_user(
                    request,
                    f"{hardware_request.pk}: {exc}",
                    level=messages.ERROR,
                )
            else:
                success_count += 1

        if success_count:
            self.message_user(
                request,
                f"Assigned boxes for {success_count} hardware request(s).",
                level=messages.SUCCESS,
            )
        return None

    @admin.action(description="Set return due date for selected requests")
    def set_return_due(self, request, queryset):
        if "apply" not in request.POST:
            return self._intermediate_action_response(
                request,
                queryset,
                "admin/hardware_requests/set_return_due_action.html",
                "Set return due date for selected hardware requests",
                "set_return_due",
            )

        form = ReturnDueForm(request.POST)
        if not form.is_valid():
            self.message_user(request, form.errors, level=messages.ERROR)
            return None

        success_count = 0
        for hardware_request in queryset:
            try:
                workflow_set_return_due(
                    request.user,
                    hardware_request,
                    form.cleaned_data["return_due_at"],
                )
            except WORKFLOW_EXCEPTIONS as exc:
                self.message_user(
                    request,
                    f"{hardware_request.pk}: {exc}",
                    level=messages.ERROR,
                )
            else:
                success_count += 1

        if success_count:
            self.message_user(
                request,
                f"Updated return due date for {success_count} hardware request(s).",
                level=messages.SUCCESS,
            )
        return None

    def _intermediate_action_response(
        self,
        request,
        queryset,
        template_name,
        title,
        action_name,
    ):
        context = {
            **self.admin_site.each_context(request),
            "title": title,
            "queryset": queryset,
            "opts": self.model._meta,
            "action_name": action_name,
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(request, template_name, context)
