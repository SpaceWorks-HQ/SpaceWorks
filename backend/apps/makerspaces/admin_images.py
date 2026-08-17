from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.utils.safestring import mark_safe
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.audit import services as audit
from apps.evidence.storage import StorageUnavailable
from apps.inventory import public_image_storage
from apps.makerspaces.models import Makerspace


class MakerspaceAdminForm(forms.ModelForm):
    logo_upload = forms.FileField(required=False, label="Upload logo")
    clear_logo = forms.BooleanField(required=False, label="Clear logo")
    cover_upload = forms.FileField(required=False, label="Upload cover image")
    clear_cover = forms.BooleanField(required=False, label="Clear cover image")

    class Meta:
        model = Makerspace
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        for name in ("logo", "cover"):
            upload = cleaned.get(f"{name}_upload")
            if upload and cleaned.get(f"clear_{name}"):
                raise forms.ValidationError(f"Choose upload or clear {name}, not both.")
            if not upload:
                continue
            if not self.instance.pk:
                raise forms.ValidationError("Save the makerspace before uploading images.")
            if upload.size > settings.PUBLIC_IMAGE_MAX_BYTES:
                raise forms.ValidationError(
                    f"Image must be {settings.PUBLIC_IMAGE_MAX_BYTES} bytes or smaller."
                )
            try:
                cleaned[f"_{name}_ext"] = public_image_storage.ext_for(
                    upload.content_type,
                    upload.name,
                )
            except DRFValidationError as exc:
                raise forms.ValidationError(str(exc.detail)) from exc
        return cleaned


class MakerspaceImageAdminMixin:
    @admin.display(description="Logo preview")
    def logo_preview(self, obj):
        return self._image_preview(obj.logo_key if obj else "")

    @admin.display(description="Cover preview")
    def cover_preview(self, obj):
        return self._image_preview(obj.cover_image_key if obj else "")

    def _image_preview(self, object_key):
        url = public_image_storage.public_url(object_key)
        if not url:
            return "(no image)"
        return mark_safe(
            f'<img src="{url}" alt="" style="max-width: 180px; max-height: 120px;" />'
        )

    def save_model(self, request, obj, form, change):
        old_logo = old_cover = ""
        if change and obj.pk:
            old = type(obj).objects.only("logo_key", "cover_image_key").get(pk=obj.pk)
            old_logo = old.logo_key
            old_cover = old.cover_image_key

        uploads = self._upload_public_images(request, obj, form)
        clears = self._clear_public_images(obj, form, old_logo, old_cover)
        super().save_model(request, obj, form, change)
        self._finish_image_uploads(request, obj, uploads, old_logo, old_cover)
        self._finish_image_clears(request, obj, clears)

    def _upload_public_images(self, request, obj, form):
        uploads = []
        for name, field in (("logo", "logo_key"), ("cover", "cover_image_key")):
            upload = form.cleaned_data.get(f"{name}_upload")
            if not upload:
                continue
            key = public_image_storage.build_object_key(
                "makerspace",
                obj.id,
                form.cleaned_data[f"_{name}_ext"],
            )
            try:
                public_image_storage.put_bytes(key, upload.read(), upload.content_type)
            except StorageUnavailable:
                # Raising from save_model() would 500 (Django admin does not turn it
                # into a form error). Skip this image, keep other edits, warn the user.
                self.message_user(
                    request,
                    f"Public image storage is unavailable; the {name} was not saved.",
                    level=messages.ERROR,
                )
                continue
            setattr(obj, field, key)
            uploads.append((name, field, key))
        return uploads

    def _clear_public_images(self, obj, form, old_logo, old_cover):
        clears = []
        if form.cleaned_data.get("clear_logo"):
            obj.logo_key = ""
            clears.append(("logo", old_logo))
        if form.cleaned_data.get("clear_cover"):
            obj.cover_image_key = ""
            clears.append(("cover", old_cover))
        return clears

    def _finish_image_uploads(self, request, obj, uploads, old_logo, old_cover):
        for name, field, key in uploads:
            old_key = old_logo if field == "logo_key" else old_cover
            if old_key and old_key != key:
                public_image_storage.delete_public_image_on_commit(obj, old_key)
            audit.record(
                request.user,
                f"makerspace.{name if name == 'logo' else 'cover'}_attached",
                makerspace=obj,
                target=obj,
            )

    def _finish_image_clears(self, request, obj, clears):
        for name, old_key in clears:
            if old_key:
                public_image_storage.delete_public_image_on_commit(obj, old_key)
            audit.record(
                request.user,
                f"makerspace.{name if name == 'logo' else 'cover'}_cleared",
                makerspace=obj,
                target=obj,
            )
