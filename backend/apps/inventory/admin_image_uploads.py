from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.utils.safestring import mark_safe
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.audit import services as audit
from apps.evidence.storage import StorageUnavailable
from apps.inventory import public_image_storage


class PublicImageAdminForm(forms.ModelForm):
    image_upload = forms.FileField(required=False, label="Upload image")
    clear_image = forms.BooleanField(required=False, label="Clear current image")

    image_field = ""
    image_kind = ""

    def clean(self):
        cleaned = super().clean()
        upload = cleaned.get("image_upload")
        if upload and cleaned.get("clear_image"):
            raise forms.ValidationError("Choose upload or clear image, not both.")
        if upload:
            if not self.instance.pk:
                raise forms.ValidationError("Save the object before uploading an image.")
            if upload.size > settings.PUBLIC_IMAGE_MAX_BYTES:
                raise forms.ValidationError(
                    f"Image must be {settings.PUBLIC_IMAGE_MAX_BYTES} bytes or smaller."
                )
            try:
                cleaned["_image_ext"] = public_image_storage.ext_for(
                    upload.content_type,
                    upload.name,
                )
            except DRFValidationError as exc:
                raise forms.ValidationError(str(exc.detail)) from exc
        return cleaned


class PublicImageAdminMixin:
    image_field = ""
    image_kind = ""
    image_attach_action = ""
    image_clear_action = ""

    @admin.display(description="Image preview")
    def image_preview(self, obj):
        object_key = getattr(obj, self.image_field, "")
        url = public_image_storage.public_url(object_key)
        if not url:
            return "(no image)"
        return mark_safe(
            f'<img src="{url}" alt="" style="max-width: 180px; max-height: 120px;" />'
        )

    def save_model(self, request, obj, form, change):
        old_key = ""
        if change and obj.pk:
            old = type(obj).objects.only(self.image_field).get(pk=obj.pk)
            old_key = getattr(old, self.image_field)

        upload = form.cleaned_data.get("image_upload")
        clear = form.cleaned_data.get("clear_image")
        if upload:
            ext = form.cleaned_data["_image_ext"]
            key = public_image_storage.build_object_key(
                self.image_kind,
                obj.makerspace_id if self.image_kind != "makerspace" else obj.id,
                ext,
            )
            data = upload.read()
            try:
                public_image_storage.put_bytes(key, data, upload.content_type)
            except StorageUnavailable:
                # Django admin does not convert save_model() exceptions into form
                # errors, so raising here would 500. Persist the object's other
                # edits WITHOUT the image and surface a recoverable message instead.
                self.message_user(
                    request,
                    "Public image storage is unavailable; the image was not saved.",
                    level=messages.ERROR,
                )
                super().save_model(request, obj, form, change)
                return
            setattr(obj, self.image_field, key)
            super().save_model(request, obj, form, change)
            if old_key and old_key != key:
                public_image_storage.delete_public_image_on_commit(
                    obj if self.image_kind == "makerspace" else obj.makerspace,
                    old_key,
                )
            audit.record(
                request.user,
                self.image_attach_action,
                makerspace=obj if self.image_kind == "makerspace" else obj.makerspace,
                target=obj,
            )
            return

        if clear:
            setattr(obj, self.image_field, "")
            super().save_model(request, obj, form, change)
            if old_key:
                public_image_storage.delete_public_image_on_commit(
                    obj if self.image_kind == "makerspace" else obj.makerspace,
                    old_key,
                )
            audit.record(
                request.user,
                self.image_clear_action,
                makerspace=obj if self.image_kind == "makerspace" else obj.makerspace,
                target=obj,
            )
            return

        super().save_model(request, obj, form, change)
