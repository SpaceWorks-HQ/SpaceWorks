import segno
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db import transaction
from django.template.response import TemplateResponse
from django.utils.safestring import mark_safe
from rest_framework.exceptions import APIException
from unfold.admin import ModelAdmin

from apps.boxes.models import Box, BoxScan, QrCode, QrScanEvent
from apps.boxes.qr_render import render_qr_label_svg
from apps.boxes.rebind import rebind_qr_target
from apps.boxes.serializers import QrRebindTargetSerializer
from apps.boxes.services import revoke_qr_code
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset
from config.admin_access import SuperuserOnlyModelAdmin
from apps.encryption.admin_search import ScopedPiiAdminSearchMixin


class QrRebindAdminForm(forms.Form):
    target_type = forms.ChoiceField(
        choices=[
            (QrCode.TargetType.PRODUCT, "Product"),
            (QrCode.TargetType.ASSET, "Asset"),
        ]
    )
    product_target = forms.ModelChoiceField(queryset=InventoryProduct.objects.none(), required=False)
    asset_target = forms.ModelChoiceField(queryset=InventoryAsset.objects.none(), required=False)
    destination_makerspace = forms.ModelChoiceField(queryset=Makerspace.objects.none(), required=False)
    destination_product = forms.ModelChoiceField(queryset=InventoryProduct.objects.none(), required=False)
    new_name = forms.CharField(required=False, max_length=100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        visible_spaces = servable_queryset(Makerspace.objects.filter(
            superadmin_access_enabled=True,
        )).order_by("name")
        visible_space_ids = visible_spaces.values("id")
        visible_products = InventoryProduct.objects.select_related("makerspace").filter(
            makerspace_id__in=visible_space_ids,
            is_archived=False,
        ).order_by("makerspace__name", "name")
        self.fields["destination_makerspace"].queryset = visible_spaces
        self.fields["product_target"].queryset = visible_products
        self.fields["destination_product"].queryset = visible_products
        self.fields["asset_target"].queryset = (
            InventoryAsset.objects.select_related("makerspace", "product")
            .filter(makerspace_id__in=visible_space_ids)
            .order_by("makerspace__name", "asset_tag")
        )

    def clean(self):
        cleaned = super().clean()
        target_type = cleaned.get("target_type")
        if target_type == QrCode.TargetType.PRODUCT and not cleaned.get("product_target"):
            raise forms.ValidationError("Select a product target.")
        if target_type == QrCode.TargetType.ASSET and not cleaned.get("asset_target"):
            raise forms.ValidationError("Select an asset target.")
        destination_product = cleaned.get("destination_product")
        destination_makerspace = cleaned.get("destination_makerspace")
        if (
            destination_product
            and destination_makerspace
            and destination_product.makerspace_id != destination_makerspace.id
        ):
            raise forms.ValidationError(
                "Destination product must belong to the destination makerspace."
            )
        return cleaned

    def rebind_payload(self):
        target_type = self.cleaned_data["target_type"]
        target = (
            self.cleaned_data["product_target"]
            if target_type == QrCode.TargetType.PRODUCT
            else self.cleaned_data["asset_target"]
        )
        payload = {
            "target_type": target_type,
            "target_id": target.id,
            "new_name": self.cleaned_data.get("new_name", ""),
        }
        if self.cleaned_data.get("destination_makerspace"):
            payload["destination_makerspace_id"] = self.cleaned_data[
                "destination_makerspace"
            ].id
        if self.cleaned_data.get("destination_product"):
            payload["destination_product_id"] = self.cleaned_data["destination_product"].id
        return payload


@admin.register(Box)
class BoxAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("label", "makerspace", "parent", "code", "is_active", "updated_at")
    list_filter = ("makerspace", "is_active")
    search_fields = ("label", "code", "location")
    autocomplete_fields = ("makerspace", "parent")
    readonly_fields = ("code", "qr_preview", "created_at", "updated_at")

    def qr_preview(self, obj):
        if not obj or not obj.pk:
            return "(save first to generate the QR)"
        return mark_safe(segno.make(obj.code).svg_inline(scale=4))

    qr_preview.short_description = "QR tag"


@admin.register(QrCode)
class QrCodeAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    actions = ["revoke_selected", "rebind_selected"]
    list_display = ("payload", "makerspace", "target_type", "target_id", "status", "updated_at")
    list_filter = ("makerspace", "target_type", "status")
    search_fields = ("payload",)
    readonly_fields = ("payload", "qr_preview", "created_at", "updated_at", "revoked_at")

    def qr_preview(self, obj):
        if not obj or not obj.pk:
            return "(no QR)"
        return mark_safe(render_qr_label_svg(obj.payload))

    qr_preview.short_description = "QR preview"

    @admin.action(description="Revoke selected QR codes")
    def revoke_selected(self, request, queryset):
        succeeded, skipped = 0, 0
        for qr in queryset:
            try:
                revoke_qr_code(request.user, qr)
            except APIException as exc:
                skipped += 1
                self.message_user(
                    request,
                    f"{qr.pk}: {_api_exception_message(exc)}",
                    level=messages.WARNING,
                )
            else:
                succeeded += 1
        self.message_user(
            request,
            f"Revoked {succeeded} QR code(s); skipped {skipped}.",
            level=messages.SUCCESS if succeeded else messages.WARNING,
        )

    @admin.action(description="Rebind selected QR code")
    def rebind_selected(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one QR code to rebind.", level=messages.ERROR)
            return None

        qr = queryset.first()
        if "apply" not in request.POST:
            form = QrRebindAdminForm()
            return self._rebind_response(request, queryset, form)

        form = QrRebindAdminForm(request.POST)
        if not form.is_valid():
            self.message_user(request, form.errors, level=messages.ERROR)
            return None

        serializer = QrRebindTargetSerializer(data=form.rebind_payload())
        if not serializer.is_valid():
            self.message_user(request, serializer.errors, level=messages.ERROR)
            return None

        try:
            with transaction.atomic():
                result = rebind_qr_target(request.user, qr.pk, serializer.validated_data)
        except APIException as exc:
            self.message_user(request, _api_exception_message(exc), level=messages.ERROR)
        else:
            self.message_user(
                request,
                f"Rebound QR {result.qr.payload}.",
                level=messages.SUCCESS,
            )
        return None

    def _rebind_response(self, request, queryset, form):
        context = {
            **self.admin_site.each_context(request),
            "title": "Rebind QR code",
            "queryset": queryset,
            "opts": self.model._meta,
            "action_name": "rebind_selected",
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
            "form": form,
        }
        return TemplateResponse(request, "admin/boxes/rebind_qr.html", context)


@admin.register(QrScanEvent)
class QrScanEventAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("qr_code", "makerspace", "context", "actor", "created_at")
    list_filter = ("makerspace", "context")
    search_fields = ("qr_code__payload",)
    readonly_fields = ("qr_code", "makerspace", "request", "actor", "context", "created_at")


@admin.register(BoxScan)
class BoxScanAdmin(ScopedPiiAdminSearchMixin, SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("box", "box_qr", "makerspace", "context", "scanned_by", "created_at")
    list_filter = ("makerspace", "context")
    search_fields = (
        "box__label",
        "box__code",
        "actor__username",
        "actor__email",
    )
    pii_search_model = "hardware_requests.HardwareRequest"
    pii_search_relation = "request__"
    pii_search_fields = ("requester_name", "requester_contact_email")
    readonly_fields = ("makerspace", "box", "request", "actor", "context", "created_at")
    fields = readonly_fields
    ordering = ("-created_at",)

    @admin.display(description="QR", ordering="box__code")
    def box_qr(self, obj):
        return obj.box.code if obj.box_id else "-"

    @admin.display(description="Scanned by", ordering="actor")
    def scanned_by(self, obj):
        return obj.actor

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def _api_exception_message(exc):
    detail = getattr(exc, "detail", None)
    if isinstance(detail, list):
        return "; ".join(str(item) for item in detail)
    if isinstance(detail, dict):
        return "; ".join(f"{key}: {value}" for key, value in detail.items())
    return str(detail or exc)
