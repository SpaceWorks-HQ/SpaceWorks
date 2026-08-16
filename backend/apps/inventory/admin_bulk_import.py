from django import forms
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse

from apps.accounts import rbac
from apps.admin_api import bulk_import
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset
from rest_framework.exceptions import ValidationError as DRFValidationError


SESSION_KEY = "admin_inventory_bulk_import_preview"


def visible_makerspaces():
    qs = servable_queryset()
    hidden = rbac.superadmin_hidden_makerspace_ids()
    return qs.exclude(id__in=hidden) if hidden else qs


class BulkImportUploadForm(forms.Form):
    makerspace = forms.ModelChoiceField(queryset=Makerspace.objects.none())
    file = forms.FileField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["makerspace"].queryset = visible_makerspaces()


def bulk_import_view(model_admin, request):
    stored = request.session.get(SESSION_KEY)
    form = BulkImportUploadForm(request.POST or None, request.FILES or None)
    preview = None

    if request.method == "POST" and "apply" in request.POST:
        if not stored:
            form.add_error(None, "Preview expired. Upload the file again.")
        else:
            makerspace = visible_makerspaces().filter(pk=stored["makerspace_id"]).first()
            if makerspace is None:
                form.add_error(None, "Makerspace is hidden or archived.")
            else:
                try:
                    require_module(makerspace, "bulk_import")
                except DRFValidationError as exc:
                    form.add_error(None, exc.detail)
                    result = None
                else:
                    result = bulk_import.apply_import(
                        request.user,
                        makerspace,
                        stored["rows"],
                        stored["mapping"],
                    )
                if result is None:
                    preview = None
                    return _render(model_admin, request, form, preview, stored)
                if result["valid"]:
                    request.session.pop(SESSION_KEY, None)
                    model_admin.message_user(
                        request,
                        f"Imported {result['created']} created and {result['updated']} updated rows.",
                    )
                    return redirect(reverse("admin:inventory_inventoryproduct_changelist"))
                preview = result

    elif request.method == "POST" and form.is_valid():
        try:
            rows = bulk_import.rows_from_upload(form.cleaned_data["file"])
        except ValueError as exc:
            form.add_error("file", str(exc))
        else:
            makerspace = form.cleaned_data["makerspace"]
            try:
                require_module(makerspace, "bulk_import")
            except DRFValidationError as exc:
                form.add_error(None, exc.detail)
            else:
                preview = bulk_import.preview_import(makerspace, rows, {})
                request.session[SESSION_KEY] = {
                    "makerspace_id": makerspace.id,
                    "rows": rows,
                    "mapping": preview["mapping"],
                }
                request.session.modified = True

    return _render(model_admin, request, form, preview, stored)


def _render(model_admin, request, form, preview, stored):
    context = {
        **model_admin.admin_site.each_context(request),
        "title": "Bulk import inventory",
        "opts": model_admin.model._meta,
        "form": form,
        "preview": preview,
        "stored_preview": stored,
    }
    return TemplateResponse(request, "admin/inventory/bulk_import.html", context)
