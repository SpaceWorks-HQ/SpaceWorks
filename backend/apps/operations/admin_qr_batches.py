"""QR batch admin follows the same first-send freeze as the staff API."""
from django.contrib import admin, messages
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from rest_framework.exceptions import ValidationError as DRFValidationError
from unfold.admin import ModelAdmin, TabularInline

from apps.accounts import rbac
from apps.audit import services as audit
from apps.operations import services
from apps.operations.models import QrPrintBatch, QrPrintBatchItem
from apps.operations.qr_zip import build_batch_zip
from config.admin_access import SuperuserOnlyModelAdmin


class QrPrintBatchItemInline(TabularInline):
    model = QrPrintBatchItem
    extra = 0

    def has_add_permission(self, request, obj=None):
        return obj is None or obj.status == QrPrintBatch.Status.DRAFT

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.status == QrPrintBatch.Status.DRAFT

    def has_delete_permission(self, request, obj=None):
        return obj is None or obj.status == QrPrintBatch.Status.DRAFT


@admin.register(QrPrintBatch)
class QrPrintBatchAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    actions = ["mark_printed_selected", "download_zip_selected"]
    list_display = ("id", "makerspace", "title", "status", "created_at", "printed_at")
    list_filter = ("status", "makerspace")
    inlines = (QrPrintBatchItemInline,)
    # Status transitions belong to mark_batch_printed, never the admin form.
    readonly_fields = ("status", "printed_at")

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            obj is None or obj.status == QrPrintBatch.Status.DRAFT
        )

    def _changeform_view(self, request, object_id, form_url, extra_context):
        # Django wraps POST change forms in atomic(). Lock before it reads the
        # current status or validates inlines, so a concurrent send has one winner.
        if request.method == "POST" and object_id is not None:
            from django.contrib.admin.utils import unquote
            from django.shortcuts import get_object_or_404

            try:
                batch_id = int(unquote(object_id))
            except (TypeError, ValueError):
                return super()._changeform_view(request, object_id, form_url, extra_context)
            queryset = rbac.scope_by_action(request.user, rbac.Action.MANAGE_QR, self.get_queryset(request))
            get_object_or_404(queryset.select_for_update(), pk=batch_id)
        return super()._changeform_view(request, object_id, form_url, extra_context)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        audit.record(request.user, "qr_print_batch.items_saved", makerspace=form.instance.makerspace,
                     target=form.instance, meta={"item_count": form.instance.items.count()})

    @admin.action(description="Mark selected QR print batches as printed")
    def mark_printed_selected(self, request, queryset):
        success_count = 0
        for batch in queryset:
            try:
                services.mark_batch_printed(request.user, batch)
            except (DRFValidationError, DjangoValidationError) as exc:
                self.message_user(request, f"{batch.pk}: {exc}", level=messages.ERROR)
            else:
                success_count += 1

        if success_count:
            self.message_user(request, f"Marked {success_count} QR print batch(es) as printed.", level=messages.SUCCESS)

    @admin.action(description="Download QR ZIP (select exactly one batch)")
    def download_zip_selected(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one batch to download.", level=messages.ERROR)
            return None

        batch = queryset.first()
        resp = HttpResponse(build_batch_zip(batch), content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="qr-batch-{batch.pk}.zip"'
        return resp
