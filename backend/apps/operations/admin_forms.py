from django import forms
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.accounts import rbac
from apps.boxes.models import Box
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset
from apps.operations.models import StocktakeLine, StocktakeSession
from apps.operations.serializers import StocktakeLineInputSerializer


def visible_makerspaces():
    qs = servable_queryset()
    hidden = rbac.superadmin_hidden_makerspace_ids()
    return qs.exclude(id__in=hidden) if hidden else qs


class StockTransferAdminForm(forms.Form):
    source_makerspace = forms.ModelChoiceField(queryset=Makerspace.objects.none())
    destination_makerspace = forms.ModelChoiceField(
        queryset=Makerspace.objects.none(),
        required=False,
        help_text="Leave blank for an in-space transfer.",
    )
    source_container = forms.ModelChoiceField(queryset=Box.objects.none(), required=False)
    destination_container = forms.ModelChoiceField(queryset=Box.objects.none(), required=False)
    product = forms.ModelChoiceField(queryset=InventoryProduct.objects.none())
    quantity = forms.IntegerField(min_value=1)
    reason = forms.CharField(widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        spaces = visible_makerspaces()
        self.fields["source_makerspace"].queryset = spaces
        self.fields["destination_makerspace"].queryset = spaces
        space_ids = spaces.values_list("id", flat=True)
        self.fields["source_container"].queryset = Box.objects.filter(
            makerspace_id__in=space_ids,
            is_active=True,
        )
        self.fields["destination_container"].queryset = Box.objects.filter(
            makerspace_id__in=space_ids,
            is_active=True,
        )
        self.fields["product"].queryset = InventoryProduct.objects.filter(
            makerspace_id__in=space_ids,
            is_archived=False,
        )

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get("source_makerspace")
        destination = cleaned.get("destination_makerspace") or source
        product = cleaned.get("product")
        if not source or not destination or not product:
            return cleaned

        self._require_visible_enabled(source, "stock_transfers")
        self._require_visible_enabled(destination, "stock_transfers")
        if product.makerspace_id != source.id:
            raise forms.ValidationError("Product must belong to the source makerspace.")
        if cleaned.get("source_container") and cleaned["source_container"].makerspace_id != source.id:
            raise forms.ValidationError("Source container must belong to the source makerspace.")
        if (
            cleaned.get("destination_container")
            and cleaned["destination_container"].makerspace_id != destination.id
        ):
            raise forms.ValidationError(
                "Destination container must belong to the destination makerspace."
            )
        if destination.id != source.id and product.tracking_mode == TrackingMode.INDIVIDUAL:
            raise forms.ValidationError(
                "Individual-tracked products cannot be moved across makerspaces."
            )
        return cleaned

    def service_payload(self):
        data = self.cleaned_data
        destination = data.get("destination_makerspace") or data["source_makerspace"]
        return {
            "source_container_id": data["source_container"].id if data["source_container"] else None,
            "destination_container_id": (
                data["destination_container"].id if data["destination_container"] else None
            ),
            "destination_makerspace_id": destination.id,
            "reason": data["reason"],
            "lines": [{"product_id": data["product"].id, "quantity": data["quantity"]}],
        }

    def _require_visible_enabled(self, makerspace, module):
        if not visible_makerspaces().filter(pk=makerspace.pk).exists():
            raise forms.ValidationError("Makerspace is hidden or archived.")
        try:
            require_module(makerspace, module)
        except DRFValidationError as exc:
            raise forms.ValidationError(exc.detail) from exc


class StocktakeCountAdminForm(forms.Form):
    product = forms.ModelChoiceField(queryset=InventoryProduct.objects.none(), required=False)
    asset = forms.ModelChoiceField(queryset=InventoryAsset.objects.none(), required=False)
    container = forms.ModelChoiceField(queryset=Box.objects.none(), required=False)
    counted_quantity = forms.IntegerField(min_value=0)
    condition = forms.ChoiceField(choices=StocktakeLine.Condition.choices)
    notes = forms.CharField(required=False, widget=forms.Textarea)

    def __init__(self, *args, stocktake: StocktakeSession, **kwargs):
        super().__init__(*args, **kwargs)
        self.stocktake = stocktake
        self.fields["product"].queryset = InventoryProduct.objects.filter(
            makerspace=stocktake.makerspace,
            is_archived=False,
        )
        self.fields["asset"].queryset = InventoryAsset.objects.filter(
            makerspace=stocktake.makerspace,
        )
        self.fields["container"].queryset = Box.objects.filter(
            makerspace=stocktake.makerspace,
            is_active=True,
        )

    def clean(self):
        cleaned = super().clean()
        payload = self.service_payload(cleaned)
        serializer = StocktakeLineInputSerializer(data=payload)
        if not serializer.is_valid():
            raise forms.ValidationError(serializer.errors)
        cleaned["_validated_payload"] = serializer.validated_data
        return cleaned

    def service_payload(self, data=None):
        data = data or self.cleaned_data
        payload = {
            "counted_quantity": data.get("counted_quantity"),
            "condition": data.get("condition"),
            "notes": data.get("notes", ""),
        }
        if data.get("product"):
            payload["product_id"] = data["product"].id
        if data.get("asset"):
            payload["asset_id"] = data["asset"].id
        if data.get("container"):
            payload["container_id"] = data["container"].id
        return payload
